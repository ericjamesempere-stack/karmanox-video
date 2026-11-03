import io
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title='KarmaClip AI V2', page_icon='🎬', layout='wide')
st.title('🎬 KarmaClip AI V2')
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


def create_scenes(lyrics, duration, style, ratio, idea):
    lines = [line.strip() for line in lyrics.splitlines()
             if line.strip() and not re.match(r'^\[.*\]$', line.strip())]
    count = min(240, max(1, math.ceil(duration / SCENE_SECONDS)))
    result = []
    for index in range(count):
        start = index * SCENE_SECONDS
        end = min(duration, start + SCENE_SECONDS)
        first = math.floor(index * len(lines) / count)
        last = max(first + 1, math.ceil((index + 1) * len(lines) / count))
        excerpt = ' / '.join(lines[first:last]) if lines else idea
        prompt = (
            f'Professional {style.lower()} music video, {ratio}. '
            f'Scene {index + 1}, duration {end - start:.1f} seconds. '
            f'Visual narrative inspired by: {excerpt or idea or "a cinematic journey"}. '
            'Single continuous cinematic shot, realistic subject motion, expressive actions, '
            'consistent character identity, outfit, environment and lighting. '
            'No subtitles, no logos, no text, no watermark.'
        )
        result.append({'start': start, 'end': end, 'lyrics': excerpt,
                       'prompt': prompt, 'image': None, 'video': None,
                       'last_frame': None, 'engine': next(iter(SERVICES))})
    return result


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
    style = st.selectbox('Style', STYLES)
    ratio = st.selectbox('Format', list(RATIOS))
    reference = st.file_uploader('Image du personnage (facultative)',
                                 type=['png', 'jpg', 'jpeg', 'webp'])
    if reference:
        st.image(reference.getvalue(), width=200)
    if st.button('✨ Préparer toutes les scènes', type='primary', use_container_width=True):
        if not lyrics.strip() and not idea.strip():
            st.warning('Ajoute des paroles ou une idée de clip.')
        else:
            st.session_state.scenes = create_scenes(lyrics, duration, style, ratio, idea)
            st.session_state.clip = None
            st.success(f'{len(st.session_state.scenes)} scènes préparées !')

with st.container(border=True):
    st.subheader('2. Paramètres de production')
    automatic = st.checkbox('Production automatique (si connecteurs disponibles)', value=False)
    fallback = st.checkbox('Basculement automatique entre moteurs compatibles', value=True)
    continuity = st.checkbox('Continuité entre les scènes', value=True)
    st.caption('Lore Motion est prioritaire. Aucun connecteur automatique vérifié n’est installé. '
               'Les moteurs s’ouvrent en mode manuel. La case automatique est décochée au démarrage.')
    if automatic:
        st.warning('Aucun connecteur vidéo automatique actif : la production externe reste manuelle.')
    with st.expander('🌐 Tous les moteurs disponibles'):
        for name, url in SERVICES.items():
            st.link_button('Ouvrir ' + name, url, use_container_width=True)

if st.session_state.scenes:
    scenes = st.session_state.scenes
    st.subheader(f'3. Tes scènes ({len(scenes)})')
    st.caption('Répartition approximative des paroles : la synchronisation mot à mot nécessite des paroles horodatées.')
    st.markdown("### Production de scènes sélectionnées")
    st.caption("Lore Motion est prioritaire mais n'a pas d'API vérifiée ici. LTX peut être tenté directement : disponibilité non garantie.")
    missing = [i for i, scene in enumerate(scenes) if not scene["video"]]
    chosen = st.multiselect("Scènes à traiter", list(range(len(scenes))), default=missing,
                            format_func=lambda i: f"Scène {i+1:02d} ({scenes[i]['start']:.0f}–{scenes[i]['end']:.0f}s)")
    mode = st.radio("Mode de production", ["Lore Motion (manuel)", "LTX (tentative automatique)"])
    if chosen:
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for j in chosen:
                archive.writestr(f"scene_{j+1:02d}.txt", scenes[j]["prompt"])
        st.download_button("Télécharger tous les prompts sélectionnés", buffer.getvalue(),
                           "prompts_karmaclip.zip", "application/zip")
    if st.button("Générer les scènes sélectionnées", disabled=not chosen, use_container_width=True):
        if mode.startswith("Lore Motion"):
            st.warning("Lore Motion ne peut pas être lancé automatiquement depuis cette application sans API ou navigateur autorisé. Les prompts sont prêts à copier.")
            st.link_button("Ouvrir Lore Motion", "https://loremotion.com/")
        else:
            bar = st.progress(0)
            for position, j in enumerate(chosen):
                if scenes[j]["video"]:
                    bar.progress((position + 1) / len(chosen))
                    continue
                try:
                    with st.spinner(f"Génération de la scène {j+1} via LTX…"):
                        data, extension = generate_ltx_scene(scenes[j]["prompt"])
                        scenes[j]["video"] = (data, extension)
                        scenes[j]["last_frame"] = extract_last_frame(data, extension)
                        scenes[j]["engine"] = "LTX / Hugging Face"
                except Exception as exc:
                    st.error(f"Arrêt sur la scène {j+1}. Les scènes précédentes restent enregistrées dans cette session. {exc}")
                    break
                bar.progress((position + 1) / len(chosen))
            st.success("Tentative terminée. Vérifie les vidéos ci-dessous.")

    for index, scene in enumerate(scenes):
        with st.expander(f'Scène {index + 1:02d} · {scene["start"]:.0f}–{scene["end"]:.0f} s'
                         + (' · ✅ vidéo prête' if scene['video'] else ''), expanded=(index == 0)):
            st.caption('Paroles : ' + (scene['lyrics'] or '—'))
            scene['prompt'] = st.text_area('Prompt vidéo', value=scene['prompt'],
                                           height=155, key=f'prompt_{index}')
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
            names = list(SERVICES)
            selected = st.selectbox('Moteur vidéo', names, index=names.index(scene['engine']),
                                    key=f'engine_{index}')
            scene['engine'] = selected
            st.link_button('🌐 Ouvrir ' + selected, SERVICES[selected], use_container_width=True)
            st.info('Copie le prompt, ouvre le moteur, génère la vidéo, puis importe le MP4/WEBM ci-dessous.')
            video_file = st.file_uploader('Importer la vidéo générée (MP4/WEBM)',
                                          type=['mp4', 'webm'], key=f'video_{index}')
            if video_file:
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
