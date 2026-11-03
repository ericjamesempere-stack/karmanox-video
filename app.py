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

st.set_page_config(page_title='KarmaClip AI V10.1', page_icon='🎬', layout='wide')
if "visual_reference_description" not in st.session_state:
    st.session_state.visual_reference_description = ""
if "visual_reference_input" not in st.session_state:
    st.session_state.visual_reference_input = st.session_state.visual_reference_description

st.title('🎬 KarmaClip AI V10.1')
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


@st.cache_resource(show_spinner="Chargement du modèle de vision gratuit…")
def load_free_vision():
    """Run a public, open-weight image captioner locally; no API key or account."""
    from transformers import BlipProcessor, BlipForConditionalGeneration
    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
    model.eval()
    return processor, model


def describe_image_free(image_bytes):
    """Offline inference after first model download; no third-party paid API."""
    from PIL import Image
    import torch
    processor, model = load_free_vision()
    picture = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    picture.thumbnail((512, 512))
    inputs = processor(images=picture, return_tensors="pt")
    with torch.inference_mode():
        ids = model.generate(**inputs, max_new_tokens=55, num_beams=3)
    caption = processor.decode(ids[0], skip_special_tokens=True).strip()
    if not caption:
        raise ValueError("Le modèle n'a pas pu décrire cette image.")
    return caption


def describe_image(image_bytes, mime):
    """Optional richer vision with a separately configured API key."""
    key = st.secrets.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Aucune clé OPENAI_API_KEY configurée.")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                "Describe the main visible subjects in this image accurately in concise English. "
                "Count them and identify their colors, outfits, relative positions, setting and "
                "distinguishing features. Do not invent details. Max 65 words."
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



def scene_mood(lyrics, index, count):
    """Mood is a creative cue, not a literal restatement of lyrics."""
    t = lyrics.lower()
    if any(w in t for w in ["love", "amour", "heart", "coeur", "cœur", "kiss", "together"]):
        return "romantic"
    if any(w in t for w in ["alone", "lonely", "sad", "lost", "triste", "seul", "oubli"]):
        return "melancholic"
    if any(w in t for w in ["party", "dance", "danse", "groove", "move", "fiesta"]):
        return "dance"
    if any(w in t for w in ["fight", "fire", "rage", "combat", "liberty", "liberté"]):
        return "power"
    return "dreamlike"


# Original short-film beats, not lyrics pasted into a prompt.
BEATS = {
    "dance": [
        "The characters notice each other across the dance floor, exchanging shy glances while keeping their distance",
        "Both characters begin a playful synchronized step, still dancing separately",
        "One character makes a funny exaggerated move; the other answers with a teasing dance move",
        "They circle each other in rhythm, smiling, without touching",
        "Their movements become confident and perfectly synchronized",
        "They reach toward one another and finally join hands, dancing together",
    ],
    "romantic": [
        "The characters exchange a hesitant look, as if recognizing a familiar feeling",
        "One character takes a small step closer; the other responds with a warm smile",
        "They move around each other in a playful, gentle rhythm",
        "A quiet pause brings their faces close; their expressions become sincere",
        "They move side by side, naturally matching each other's pace",
        "They join hands and share a joyful, spontaneous dance",
    ],
    "melancholic": [
        "The character pauses in the middle of an ordinary action, distracted by a distant memory",
        "A small object catches the character's attention; they turn it slowly in their hands",
        "The character walks past familiar surroundings, noticing what has changed",
        "They stop, look back briefly, then decide to keep moving",
        "The character lifts their head and takes a more determined step",
        "They continue forward with a subtle, genuine smile",
    ],
    "power": [
        "The character plants their feet firmly and faces an unexpected challenge",
        "They move forward with a steady, purposeful stride",
        "A sudden obstacle forces a quick, energetic reaction",
        "The character recovers balance and responds with renewed confidence",
        "They make one decisive movement that changes the situation",
        "The character stands tall, breathing deeply after the effort",
    ],
    "dreamlike": [
        "The character notices a small unexpected detail in the surroundings and turns toward it",
        "They follow the detail with curiosity, moving through the space",
        "An unusual visual change surprises the character; they react naturally",
        "They experiment with their surroundings in a playful, physical way",
        "The character makes a confident choice and changes direction",
        "The scene ends with a distinctive gesture that can connect to the next shot",
    ],
}


def image_guided_prompt(scene, style, reference_description, custom_idea="", mood="dreamlike",
                        total_scenes=1, story_idea=""):
    """Direct a visible physical action. Lyrics inform mood, not the literal text."""
    index = int(scene.get("index", 0))
    beats = BEATS.get(mood, BEATS["dreamlike"])
    if total_scenes <= 1:
        beat = beats[0]
    else:
        beat_index = min(len(beats)-1, round(index * (len(beats)-1) / (total_scenes-1)))
        beat = beats[beat_index]
    variation = [
        "A gentle tracking shot follows the movement",
        "The camera slowly moves closer as the gesture unfolds",
        "A side-angle shot emphasizes body language",
        "The camera holds steady on the characters' reaction",
        "A low-angle shot highlights the physical movement",
        "The camera follows a small change in direction",
    ][index % 6]
    action = (custom_idea or (beat + ". " + variation)).strip()
    action = re.sub(r"\\s+", " ", action)[:330]
    subjects = reference_description.strip()
    if subjects:
        identity = f"Use the uploaded reference image. Same exact subjects: {subjects}. "
        identity += "Keep the exact number of characters, faces, outfits, and colors. "
    else:
        identity = ("Use the uploaded reference image as the character and setting reference. "
                    "Do not invent or remove subjects. ")
    setting = (story_idea.strip()[:140] + ". ") if story_idea.strip() else ""
    return (f"{identity}{setting}Action: {action}. "
            f"One clear physical action, expressive natural movement, {style}, "
            "single continuous shot, no captions, no new characters.")


def create_scenes(lyrics, duration, style, ratio, idea, scene_length=5):
    lines = [line.strip() for line in lyrics.splitlines()
             if line.strip() and not re.match(r'^\\[.*\\]$', line.strip())]
    count = min(240, max(1, math.ceil(duration / scene_length)))
    result = []
    for index in range(count):
        start = index * scene_length
        end = min(duration, start + scene_length)
        first = math.floor(index * len(lines) / count)
        last = max(first + 1, math.ceil((index + 1) * len(lines) / count))
        excerpt = ' / '.join(lines[first:last]) if lines else ""
        result.append({'index': index, 'start': start, 'end': end, 'lyrics': excerpt,
                       'prompt': '', 'scene_idea': '', 'image': None, 'video': None,
                       'last_frame': None, 'engine': next(iter(SERVICES))})
    return result


def creative_storyboard_with_ai(scenes, lyrics, reference_description, idea, style, image_bytes=None, mime=None):
    """Optional AI director. Image supplied to vision model when configured."""
    key = st.secrets.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Le réalisateur IA nécessite une clé API configurée.")
    image_part = []
    if image_bytes:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        image_part = [{"type": "image_url", "image_url": {
            "url": f"data:{mime or 'image/jpeg'};base64,{encoded}", "detail": "low"
        }}]
    brief = (
        "You are an inventive music-video director. Create a coherent visual narrative "
        "with concrete actions by the EXACT characters in the reference image. "
        "Never paraphrase, illustrate literally, quote or repeat song lyrics. "
        "Translate the song's emotional journey into a playful, meaningful sequence of "
        "VISUAL ACTIONS and evolving character relationships. "
        "Respect all subjects, exact character count, outfits and appearance. "
        "Each shot is about 5 seconds, a single physically achievable action. "
        "Prompts concise (max 42 words), in English, visually specific, different "
        "from one another, no text overlays. "
        "Return ONLY JSON object with key 'prompts' holding an array of strings, "
        f"exactly {len(scenes)} items.\n"
        f"Characters description: {reference_description}\n"
        f"Creative direction: {idea}\nStyle: {style}\n"
        f"Lyrics (for emotional arc only): {lyrics[:11000]}\n"
        f"Scene excerpts: {json.dumps([x['lyrics'] for x in scenes], ensure_ascii=False)}"
    )
    payload = {"model": "gpt-4o-mini", "messages": [
        {"role": "user", "content": [{"type": "text", "text": brief}] + image_part}
    ], "response_format": {"type": "json_object"}, "max_tokens": min(12000, max(1500, len(scenes)*85))}
    response = requests.post("https://api.openai.com/v1/chat/completions",
                             headers={"Authorization": f"Bearer {key}"},
                             json=payload, timeout=120)
    response.raise_for_status()
    prompts = json.loads(response.json()["choices"][0]["message"]["content"])["prompts"]
    if len(prompts) != len(scenes) or not all(isinstance(p,str) for p in prompts):
        raise ValueError("Le réalisateur IA n'a pas renvoyé le bon nombre de scènes.")
    return prompts


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
    # Apply AI output before the text widget is instantiated (Streamlit rule).
    if "visual_reference_pending" in st.session_state:
        st.session_state.visual_reference_input = st.session_state.pop("visual_reference_pending")
    st.text_area(
        "🖼️ Description des personnages de l'image (commune à toutes les scènes)",
        placeholder="Ex. Two anthropomorphic bananas: one in a black suit, one in a red evening dress. Both dancing at a party.",
        height=95, key="visual_reference_input"
    )
    st.session_state.visual_reference_description = st.session_state.visual_reference_input
    if reference:
        st.caption("Analyse gratuite : modèle BLIP local, sans clé API. Le premier lancement télécharge le modèle et peut être lent ou dépasser la mémoire de Streamlit Cloud.")
        col_free, col_plus = st.columns(2)
        with col_free:
            free_click = st.button("🔎 Analyser gratuitement", use_container_width=True)
        with col_plus:
            plus_click = st.button("✨ Analyse avancée (API)", use_container_width=True)
        if free_click:
            try:
                with st.spinner("Analyse de l'image en cours…"):
                    description = describe_image_free(reference.getvalue())
                st.session_state.visual_reference_pending = description
                st.success("Description créée. Vérifie le nombre de personnages et les vêtements.")
                st.rerun()
            except ImportError:
                st.error("Modèle gratuit non installé. Ajoute les dépendances du fichier requirements_V10.txt à requirements.txt.")
            except Exception as exc:
                st.warning(f"Analyse locale indisponible : {exc}. Tu peux toujours décrire l'image manuellement.")
        if plus_click:
            try:
                st.session_state.visual_reference_pending = describe_image(
                    reference.getvalue(), reference.type or "image/jpeg"
                )
                st.rerun()
            except Exception as exc:
                st.warning(f"Analyse avancée indisponible : {exc}")
    st.selectbox("🎭 Ambiance de réalisation", [
        "Automatique selon la chanson", "Danse et humour", "Romantique",
        "Mélancolique", "Énergie et dépassement", "Onirique et surprenant"
    ], key="director_mood")
    st.caption("Le réalisateur transforme les émotions de la chanson en actions à l'écran ; il ne recopie pas les paroles.")
    if reference:
        st.caption("L'image de départ est jointe aux exports. Pour une fidélité visuelle réelle, choisis un moteur image-vers-vidéo et fournis-lui cette image.")
    if st.button('✨ Préparer toutes les scènes', type='primary', use_container_width=True):
        if not lyrics.strip() and not idea.strip() and not reference:
            st.warning('Ajoute des paroles, une idée ou une image.')
        else:
            st.session_state.scenes = create_scenes(lyrics, duration, style, ratio, idea or ('Animate the provided reference character in a cinematic scene' if reference else ''), scene_length)
            moods = {
                "Danse et humour": "dance", "Romantique": "romantic",
                "Mélancolique": "melancholic", "Énergie et dépassement": "power",
                "Onirique et surprenant": "dreamlike"
            }
            selected_mood = moods.get(st.session_state.director_mood,
                                      scene_mood(lyrics + " " + idea, 0, len(st.session_state.scenes)))
            st.session_state.current_mood = selected_mood
            for generated_scene in st.session_state.scenes:
                generated_scene["prompt"] = image_guided_prompt(
                    generated_scene, style, st.session_state.visual_reference_description,
                    mood=selected_mood, total_scenes=len(st.session_state.scenes),
                    story_idea=idea
                )
            for k in list(st.session_state.keys()):
                if re.fullmatch(r"prompt_\\d+", k):
                    del st.session_state[k]
            st.session_state.clip = None
            st.session_state.scene_selection = []
            st.session_state.select_all = False
            st.success(f'{len(st.session_state.scenes)} scènes préparées !')
    if st.session_state.scenes and st.button("🎬 Réalisation IA avancée (facultatif, clé API nécessaire)",
                                             use_container_width=True):
        try:
            with st.spinner("Le réalisateur imagine des actions et une histoire visuelle…"):
                prompts = creative_storyboard_with_ai(
                    st.session_state.scenes, lyrics, st.session_state.visual_reference_description,
                    idea, style, reference.getvalue() if reference else None,
                    reference.type if reference else None
                )
                for j, prompt in enumerate(prompts):
                    st.session_state.scenes[j]["prompt"] = prompt
                    st.session_state[f"prompt_{j}"] = prompt
            st.rerun()
        except Exception as exc:
            st.error(f"Réalisateur IA indisponible : {exc}")


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
    st.info("Chaque prompt raconte une action visible. Les paroles orientent l'émotion, pas le texte du prompt. Tu peux remplacer chaque action par ton idée.")

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
                new_prompt = image_guided_prompt(scene, style, st.session_state.visual_reference_description,
                                               scene['scene_idea'],
                                               mood=st.session_state.get('current_mood', 'dreamlike'),
                                               total_scenes=len(scenes), story_idea=idea)
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
    st.caption("Lore Motion est prioritaire mais n'a pas d'API vérifiée ici. LTX peut être tenté directement : disponibilité non garantie.")
    if "scene_selection" not in st.session_state:
        st.session_state.scene_selection = []
    if "select_all" not in st.session_state:
        st.session_state.select_all = False
    def update_all():
        st.session_state.scene_selection = (list(range(len(st.session_state.scenes)))
                                            if st.session_state.select_all else [])
    def update_individual():
        st.session_state.select_all = len(st.session_state.scene_selection) == len(st.session_state.scenes)
    st.checkbox("☑️ Sélectionner toutes les scènes", key="select_all", on_change=update_all)
    chosen = st.multiselect(
        "Scènes sélectionnées (aucune par défaut)", list(range(len(scenes))),
        format_func=lambda i: f"Scène {i+1:02d} ({scenes[i]['start']:.0f}–{scenes[i]['end']:.0f}s)",
        key="scene_selection", on_change=update_individual)
    if automatic:
        mode = "LTX (tentative automatique)"
        st.info("Mode automatique expérimental : LTX génère les scènes une par une. Lore Motion ne dispose pas ici d'un connecteur automatique autorisé et vérifié.")
    else:
        mode = "Lore Motion (manuel)"
        st.info("Mode manuel : ouvre le moteur de chaque scène, copie son prompt et importe le MP4 obtenu. Tu peux aussi sélectionner plusieurs scènes pour télécharger tous leurs prompts.")
    if chosen:
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for j in chosen:
                archive.writestr(f"scene_{j+1:02d}.txt", scenes[j]["prompt"])
                if st.session_state.visual_reference_description:
                    archive.writestr("personnages_reference.txt", st.session_state.visual_reference_description)
                image_data = scenes[j].get("image")
                if not image_data and continuity and j > 0:
                    image_data = scenes[j-1].get("last_frame")
                if not image_data and reference:
                    image_data = reference.getvalue()
                if image_data:
                    archive.writestr(f"scene_{j+1:02d}_reference.png", image_data)
        st.download_button("Télécharger tous les prompts sélectionnés", buffer.getvalue(),
                           "prompts_karmaclip.zip", "application/zip")
    retries = st.slider('Tentatives maximum par scène (LTX)', 1, 3, 2) if automatic else 2
    st.caption("Les sites tiers ne peuvent pas être préremplis automatiquement depuis Streamlit sans API compatible. Le ZIP contient désormais les prompts ET les images à fournir.")

    if st.button("🎬 Lancer les scènes sélectionnées" if automatic else "📋 Préparer les scènes sélectionnées", disabled=not chosen, use_container_width=True):
        if mode.startswith("Lore Motion"):
            st.warning("Lore Motion ne peut pas être lancé automatiquement depuis cette application sans API ou navigateur autorisé. Les prompts sont prêts à copier.")
            st.link_button("Ouvrir Lore Motion", "https://loremotion.com/")
        else:
            bar = st.progress(0)
            for position, j in enumerate(chosen):
                if scenes[j]["video"]:
                    bar.progress((position + 1) / len(chosen))
                    continue
                error = None
                for attempt in range(retries):
                    try:
                        with st.spinner(f"Scène {j+1} — tentative {attempt+1}/{retries} via LTX…"):
                            data, extension = generate_ltx_scene(scenes[j]["prompt"])
                            scenes[j]["video"] = (data, extension)
                            scenes[j]["last_frame"] = extract_last_frame(data, extension)
                            scenes[j]["engine"] = "LTX / Hugging Face"
                            error = None
                            break
                    except Exception as exc:
                        error = exc
                if error is not None:
                    st.error(f"Arrêt scène {j+1}. Scènes déjà générées conservées dans cette session. {error}")
                    if fallback:
                        st.info('Choisis un autre moteur dans la fiche de cette scène, puis importe sa vidéo pour reprendre.')
                    break
                bar.progress((position + 1) / len(chosen))
            if all(scene['video'] for scene in scenes):
                st.success('Toutes les scènes sont prêtes ! Tu peux assembler le clip ci-dessous.')
            else:
                st.info('Production interrompue ou partielle. Les vidéos terminées restent disponibles dans cette session.')

    completed = [(i, scene) for i, scene in enumerate(scenes) if scene['video']]
    st.progress(len(completed) / len(scenes), text=f"{len(completed)}/{len(scenes)} vidéos générées ou importées")
    if completed:
        import zipfile
        backup = io.BytesIO()
        with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_STORED) as zf:
            for i, scene in completed:
                data, ext = scene['video']
                zf.writestr(f'scene_{i+1:03d}{ext}', data)
                if scene['last_frame']:
                    zf.writestr(f'scene_{i+1:03d}_last.png', scene['last_frame'])
        st.download_button('💾 Sauvegarder les scènes terminées (ZIP)', backup.getvalue(),
                           'karmaclip_scenes.zip', 'application/zip', use_container_width=True)
    st.markdown("### 4. Sauvegarde et montage")
    st.caption("Sauvegarde les vidéos en ZIP avant de fermer l'onglet : Streamlit Cloud ne garantit pas la conservation de la session.")
    restore = st.file_uploader("Restaurer des vidéos d'un ZIP de sauvegarde (facultatif)", type=["zip"], key="restore_zip")
    if restore and st.button("📥 Restaurer les scènes du ZIP"):
        import zipfile
        restored = 0
        try:
            with zipfile.ZipFile(io.BytesIO(restore.getvalue())) as archive:
                for filename in archive.namelist():
                    match = re.fullmatch(r"scene_(\d+)\.(mp4|webm)", Path(filename).name)
                    if not match:
                        continue
                    j = int(match.group(1)) - 1
                    if 0 <= j < len(scenes):
                        raw = archive.read(filename)
                        scenes[j]["video"] = (raw, "." + match.group(2))
                        scenes[j]["last_frame"] = extract_last_frame(raw, "." + match.group(2))
                        restored += 1
            st.success(f"{restored} scènes restaurées.")
            st.rerun()
        except Exception as exc:
            st.error(f"Restauration impossible : {exc}")

    project = {'title': title, 'artist': artist, 'duration': duration,
               'style': style, 'ratio': ratio, 'priority': 'Lore Motion',
               'fallback': fallback, 'continuity': continuity,
               'scenes': [{k: v for k, v in scene.items()
                           if k not in ('image', 'video', 'last_frame')}
                          for scene in scenes]}
    st.download_button('📦 Télécharger le storyboard JSON',
                       json.dumps(project, ensure_ascii=False, indent=2),
                       file_name='karmaclip_storyboard.json', mime='application/json',
                       use_container_width=True)
    if st.button('🎞️ Assembler le clip final', type='primary', use_container_width=True):
        try:
            with st.spinner('Montage du clip en cours…'):
                st.session_state.clip = assemble_clip(scenes, music, music_ext, ratio)
            st.success('Clip final terminé !')
        except Exception as error:
            st.error(str(error))
    if st.session_state.clip:
        st.video(st.session_state.clip)
        st.download_button('⬇️ Télécharger le clip MP4', st.session_state.clip,
                           file_name='karmaclip_final.mp4', mime='video/mp4',
                           use_container_width=True)
else:
    st.info('Commence par préparer les scènes à partir de ta chanson.')

st.caption('Les services vidéo externes peuvent appliquer des quotas, connexions ou frais. Aucun paiement automatique.')
