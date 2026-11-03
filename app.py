
import io
import base64
import requests
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title='KarmaClip AI V8', page_icon='🎬', layout='wide')
if "visual_reference_description" not in st.session_state:
    st.session_state.visual_reference_description = ""

st.title('🎬 KarmaClip AI V8')
st.caption('Paroles + musique → scènes de 5 secondes → vidéos → clip final')

SERVICES = {
    'Lore Motion (prioritaire)': 'https://loremotion.com/',
    'Wan2.Video': 'https://wan2.video/',
    'Wan AI': 'https://wan.video/',
    'LTX / Hugging Face': 'https://huggingface.co/spaces/Lightricks/ltx-video-distilled',
    'NiftyVid': 'https://igorcsis.github.io/nifty-vid/',
    'NOVA AI Video': 'https://novaos-original.github.io/nova-os-website/video-studio/ai-generator.html',
    'Kling': 'https://app.klingai.com/global/',
    'Vidu': 'https://www.vidu.com/',
    'Veo': 'https://labs.google/fx/tools/flow',
}
STYLES = ['Cinématique photoréaliste', 'Clip musical', 'Animation 3D', 'Fantastique', 'Vintage', 'Minimaliste']
RATIOS = {'Vertical 9:16': (360, 640), 'Horizontal 16:9': (640, 360), 'Carré 1:1': (512, 512)}
SCENE_SECONDS = 5

if 'scenes' not in st.session_state:
    st.session_state.scenes = []
if 'clip' not in st.session_state:
    st.session_state.clip = None


def ffmpeg_available():
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def audio_duration(raw, extension):
    if not raw:
        return None
    if extension == '.wav':
        try:
            import wave
            with wave.open(io.BytesIO(raw), 'rb') as source:
                return source.getnframes() / source.getframerate()
        except Exception:
            pass
    if not ffmpeg_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ('audio' + extension)
        source.write_bytes(raw)
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(source)],
            capture_output=True, text=True, timeout=40,
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None


def describe_image(image_bytes, mime):
    """Optional visual analysis using a configured OpenAI API key."""
    key = st.secrets.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Aucune clé OPENAI_API_KEY configurée dans les secrets Streamlit.")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                "Describe this reference image in concise English for a music video. "
                "Identify the exact number and type of visible main subjects, clothing, "
                "colors, appearance, relationships and setting. Do not invent details. "
                "Maximum 65 words, no instructions or markdown."
            )},
            {"type": "image_url", "image_url": {
                "url": f"data:{mime};base64,{encoded}", "detail": "low"
            }}
        ]}],
        "max_tokens": 140
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload, timeout=45
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def image_guided_prompt(scene, style, reference_description, custom_idea=""):
    action = (custom_idea or scene.get("lyrics") or "Move naturally in the scene").strip()
    action = re.sub(r"\\s+", " ", action)
    if len(action) > 210:
        action = action[:207].rsplit(" ", 1)[0] + "..."
    if reference_description.strip():
        return (
            f"Reference subjects (use the supplied image): {reference_description.strip()}. "
            f"Scene action: {action}. Keep ALL original subjects, their number, "
            f"identities, clothing and appearance unchanged. "
            f"{style}. Natural motion, single shot, no text."
        )
    return f"{action}. {style}. Natural movement, one continuous shot, no text."


def create_scenes(lyrics, duration, style, ratio, idea, scene_length=5):
    lines = [line.strip() for line in lyrics.splitlines()
             if line.strip() and not re.match(r'^\[.*\]$', line.strip())]
    count = min(240, max(1, math.ceil(duration / scene_length)))
    result = []
    for index in range(count):
        start = index * scene_length
        end = min(duration, start + scene_length)
        first = math.floor(index * len(lines) / count)
        last = max(first + 1, math.ceil((index + 1) * len(lines) / count))
        excerpt = ' / '.join(lines[first:last]) if lines else idea
        prompt = (
            f"{style}. {excerpt or idea or 'A cinematic scene'}. "
            "Natural movement, one continuous shot, no text."
        )
        result.append({'start': start, 'end': end, 'lyrics': excerpt,
                       'prompt': prompt, 'scene_idea': '', 'image': None, 'video': None,
                       'last_frame': None, 'engine': next(iter(SERVICES))})
    return result


def short_prompt(scene, style, custom_idea=""):
    """Short, editable visual instruction, without unnecessary technical prose."""
    concept = (custom_idea or scene["lyrics"] or "A cinematic moment").strip()
    concept = re.sub(r"\\s+", " ", concept)
    if len(concept) > 260:
        concept = concept[:257].rsplit(" ", 1)[0] + "..."
    return f"{concept}. {style}. Natural movement, one continuous shot, no text."


def extract_last_frame(raw, extension):
    if not ffmpeg_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ('scene' + extension)
        target = Path(tmp) / 'last.png'
        source.write_bytes(raw)
        run = subprocess.run(
            ['ffmpeg', '-y', '-sseof', '-0.08', '-i', str(source),
             '-frames:v', '1', str(target)],
            capture_output=True, timeout=60,
        )
        if run.returncode == 0 and target.exists():
            return target.read_bytes()
    return None


def generate_ltx_scene(prompt):
    """Try public LTX Gradio endpoints; fail visibly if incompatible."""
    from gradio_client import Client
    client = Client("Lightricks/ltx-video-distilled")
    errors = []
    for endpoint in ("/generate_video", "/generate"):
        try:
            result = client.predict(prompt=prompt, api_name=endpoint)
            def find_video(item):
                if isinstance(item, str):
                    path = Path(item)
                    if path.is_file() and path.suffix.lower() in (".mp4", ".webm"):
                        return path.read_bytes(), path.suffix.lower()
                if isinstance(item, dict):
                    for value in item.values():
                        found = find_video(value)
                        if found:
                            return found
                if isinstance(item, (list, tuple)):
                    for value in item:
                        found = find_video(value)
                        if found:
                            return found
                return None
            found = find_video(result)
            if found:
                return found
            errors.append(f"{endpoint}: no downloadable video returned")
        except Exception as exc:
            errors.append(f"{endpoint}: {str(exc)[:220]}")
    raise RuntimeError("LTX public interface unavailable: " + " | ".join(errors))


def assemble_clip(scenes, music, music_ext, ratio):
    if not ffmpeg_available():
        raise RuntimeError('FFmpeg et FFprobe sont nécessaires sur le serveur.')
    if not scenes or any(scene['video'] is None for scene in scenes):
        raise RuntimeError('Chaque scène doit avoir une vidéo importée.')
    width, height = RATIOS[ratio]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        clips = []
        for index, scene in enumerate(scenes):
            data, extension = scene['video']
            source = directory / f'input_{index}{extension}'
            output = directory / f'part_{index}.mp4'
            source.write_bytes(data)
            duration = max(0.1, scene['end'] - scene['start'])
            filters = (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                       f'crop={width}:{height},fps=24,setsar=1,format=yuv420p,'
                       f'tpad=stop_mode=clone:stop_duration={duration}')
            command = ['ffmpeg', '-y', '-i', str(source), '-an', '-vf', filters,
                       '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast',
                       '-crf', '24', '-movflags', '+faststart', str(output)]
            run = subprocess.run(command, capture_output=True, timeout=240)
            if run.returncode != 0:
                raise RuntimeError(f'Erreur de montage scène {index + 1}: '
                                   + run.stderr.decode(errors='replace')[-400:])
            clips.append(output)
        manifest = directory / 'list.txt'
        manifest.write_text(''.join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding='utf-8')
        silent = directory / 'silent.mp4'
        run = subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                              '-i', str(manifest), '-c', 'copy', str(silent)],
                             capture_output=True, timeout=240)
        if run.returncode != 0:
            raise RuntimeError('Assemblage des scènes impossible.')
        if not music:
            return silent.read_bytes()
        audio = directory / ('music' + music_ext)
        audio.write_bytes(music)
        output = directory / 'final.mp4'
        run = subprocess.run(['ffmpeg', '-y', '-i', str(silent), '-i', str(audio),
                              '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                              '-c:a', 'aac', '-b:a', '192k', '-shortest',
                              '-movflags', '+faststart', str(output)],
                             capture_output=True, timeout=240)
        if run.returncode != 0:
            raise RuntimeError('Impossible d’ajouter la musique au clip.')
        return output.read_bytes()


with st.container(border=True):
    st.subheader('1. Ta chanson')
    title = st.text_input('Titre', value='Mon clip')
    artist = st.text_input('Artiste', value='KarManoX')
    lyrics = st.text_area('Paroles complètes', height=180)
    idea = st.text_area('Idée ou scénario du clip (facultatif)', height=90)
    audio_file = st.file_uploader('Musique WAV ou MP3 (facultative)', type=['wav', 'mp3'])
    music = audio_file.getvalue() if audio_file else None
    music_ext = Path(audio_file.name).suffix.lower() if audio_file else ''
    detected = audio_duration(music, music_ext) if music else None
    if detected:
        st.success(f'Durée de la musique : {detected:.1f} secondes')
    manual_duration = st.number_input('Durée si aucune musique disponible (secondes)',
                                      min_value=5, max_value=1200, value=180, step=5)
    duration = detected or float(manual_duration)
    scene_length = st.selectbox("Durée des séquences (secondes)", [5, 3, 4, 6, 8, 10], index=0)
    style = st.selectbox('Style', STYLES)
    ratio = st.selectbox('Format', list(RATIOS))
    reference = st.file_uploader('Image du personnage (facultative)',
                                 type=['png', 'jpg', 'jpeg', 'webp'])
    if reference:
        st.image(reference.getvalue(), width=200)
    st.text_area(
        "🖼️ Description des personnages de l'image (commune à toutes les scènes)",
        placeholder="Ex. Two anthropomorphic bananas: one in a black suit, one in a red evening dress. Both dancing at a party.",
        height=95, key="visual_reference_description"
    )
    if reference and st.button("🔎 Analyser automatiquement mon image (si vision configurée)"):
        try:
            mime = reference.type or "image/jpeg"
            st.session_state.visual_reference_description = describe_image(reference.getvalue(), mime)
            st.success("Image analysée : vérifie la description puis prépare les scènes.")
            st.rerun()
        except Exception as exc:
            st.warning(f"Analyse automatique indisponible : {exc}")
    if reference:
        st.caption("L'image de départ est jointe aux exports. Pour une fidélité visuelle réelle, choisis un moteur image-vers-vidéo et fournis-lui cette image.")
    if st.button('✨ Préparer toutes les scènes', type='primary', use_container_width=True):
        if not lyrics.strip() and not idea.strip() and not reference:
            st.warning('Ajoute des paroles, une idée ou une image.')
        else:
            st.session_state.scenes = create_scenes(lyrics, duration, style, ratio, idea or ('Animate the provided reference character in a cinematic scene' if reference else ''), scene_length)
            for generated_scene in st.session_state.scenes:
                generated_scene["prompt"] = image_guided_prompt(
                    generated_scene, style, st.session_state.visual_reference_description
                )

            st.session_state.clip = None
            st.session_state.scene_selection = []
            st.session_state.select_all = False
            st.success(f'{len(st.session_state.scenes)} scènes préparées !')

with st.container(border=True):
    st.subheader('2. Paramètres de production')
    automatic = st.checkbox('🤖 Mode automatique', value=False, key='automatic_mode', help='Désactivé par défaut. LTX est le seul connecteur expérimental direct ; Lore Motion reste manuel.')
    fallback = st.checkbox('Proposer un autre moteur en cas d’échec', value=True)
    continuity = st.checkbox('Continuité entre les scènes (image finale → scène suivante)', value=True)
    st.info('Vidéos IA uniquement. Lore Motion reste accessible en priorité manuelle. '
            'La génération automatique expérimentale utilise LTX si son interface publique répond. '
            'La continuité par image n’est pas prise en charge par cette interface LTX.')
    with st.expander('🌐 Tous les moteurs disponibles'):
        for name, url in SERVICES.items():
            st.link_button('Ouvrir ' + name, url, use_container_width=True)

if st.session_state.scenes:
    scenes = st.session_state.scenes
    st.subheader(f'3. Tes scènes ({len(scenes)})')
    st.caption('Répartition approximative des paroles : la synchronisation mot à mot nécessite des paroles horodatées.')
    st.info("Prompts courts : chaque scène possède désormais un champ « Mon idée ». Une idée personnelle remplace la proposition automatique. Tu peux ensuite modifier librement le prompt.")

    st.markdown("### 3A. Storyboard et prompts — avant la génération")
    st.caption("Modifie chaque prompt et chaque image avant de choisir les scènes à produire.")
    for index, scene in enumerate(scenes):
        with st.expander(f'Scène {index + 1:02d} · {scene["start"]:.0f}–{scene["end"]:.0f} s'
                         + (' · ✅ vidéo prête' if scene['video'] else ''), expanded=(index == 0)):
            st.caption('Paroles : ' + (scene['lyrics'] or '—'))
            scene['scene_idea'] = st.text_area(
                '💡 Mon idée pour cette scène (facultatif)',
                value=scene.get('scene_idea', ''),
                placeholder='Ex. Deux bananes se regardent timidement en dansant.',
                height=75, key=f'scene_idea_{index}'
            )
            if st.button('✨ Créer un prompt court à partir de mon idée', key=f'build_prompt_{index}',
                         use_container_width=True):
                new_prompt = image_guided_prompt(scene, style, st.session_state.visual_reference_description, scene['scene_idea'])
                scene['prompt'] = new_prompt
                st.session_state[f'prompt_{index}'] = new_prompt
                st.rerun()
            scene['prompt'] = st.text_area('✏️ Prompt vidéo (modifiable)',
                                           value=scene['prompt'], height=105,
                                           key=f'prompt_{index}')
            st.code(scene['prompt'], language=None)
            st.caption('Appuie sur l’icône Copier du bloc ci-dessus, puis colle le prompt dans le moteur.')
            st.download_button('📋 Télécharger le prompt', scene['prompt'],
                               file_name=f'prompt_scene_{index + 1:02d}.txt',
                               mime='text/plain', key=f'prompt_file_{index}',
                               use_container_width=True)
            if continuity and index > 0 and scenes[index - 1]['last_frame']:
                frame = scenes[index - 1]['last_frame']
                st.image(frame, caption='Dernière image de la scène précédente', width=230)
                st.download_button('⬇️ Télécharger l’image de raccord', frame,
                                   file_name=f'raccord_scene_{index + 1:02d}.png',
                                   mime='image/png', key=f'raccord_{index}')
            elif reference and (index == 0 or not continuity):
                st.image(reference.getvalue(), caption='Image de référence', width=180)
            image_file = st.file_uploader('Image de départ de cette scène (facultative)',
                                          type=['png', 'jpg', 'jpeg', 'webp'], key=f'image_{index}')
            if image_file:
                scene['image'] = image_file.getvalue()
            if scene['image']:
                st.image(scene['image'], width=180)
            active_image = (scene['image'] or
                            (scenes[index-1]['last_frame'] if continuity and index > 0
                             else None) or
                            (reference.getvalue() if reference else None))
            if active_image:
                st.download_button('🖼️ Télécharger l’image à transmettre au moteur',
                                   active_image, file_name=f'image_scene_{index+1:02d}.png',
                                   mime='image/png', key=f'active_image_{index}',
                                   use_container_width=True)

            names = list(SERVICES)
            selected = st.selectbox('Moteur vidéo', names, index=names.index(scene['engine']),
                                    key=f'engine_{index}')
            scene['engine'] = selected
            st.link_button('🌐 Ouvrir ' + selected, SERVICES[selected], use_container_width=True)
            st.info('Mode manuel : copie le prompt, ouvre le moteur, génère la vidéo, puis importe le MP4/WEBM. Le moteur automatique LTX ne peut pas exploiter une image de raccord dans cette intégration.')
            video_file = st.file_uploader('Importer la vidéo générée (MP4/WEBM)',
                                          type=['mp4', 'webm'], key=f'video_{index}')
            if video_file and not scene['video']:
                data = video_file.getvalue()
                extension = Path(video_file.name).suffix.lower()
                scene['video'] = (data, extension)
                scene['last_frame'] = extract_last_frame(data, extension)
            if scene['video']:
                st.video(scene['video'][0])
                if scene['last_frame']:
                    st.image(scene['last_frame'], caption='Dernière image extraite', width=180)
                elif not ffmpeg_available():
                    st.warning('FFmpeg absent : extraction de la dernière image impossible.')

    st.markdown("### 3B. Sélection et génération")
    st.markdown("### Production de scènes sélectionnées")
    st.caption("Lore Motion est prioritaire mais n'a pas d'API vérifiée ici. LTX peut être tenté directement : disponibilité non garan
