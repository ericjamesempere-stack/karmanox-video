import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image

st.set_page_config(page_title='KarmaClip AI V2', page_icon='🎬', layout='wide')
st.title('🎬 KarmaClip AI V2')
st.caption('Paroles + musique → storyboard → scènes vidéo → clip final')

SERVICES = [
    ('Lore Motion (prioritaire)', 'https://loremotion.com/'),
    ('Wan2.Video', 'https://wan2.video/'),
    ('Wan AI', 'https://wan.video/'),
    ('LTX / Hugging Face', 'https://huggingface.co/spaces/Lightricks/ltx-video-distilled'),
    ('NiftyVid', 'https://igorcsis.github.io/nifty-vid/'),
    ('NOVA AI Video', 'https://novaos-original.github.io/nova-os-website/video-studio/ai-generator.html'),
    ('Kling', 'https://app.klingai.com/global/'),
    ('Vidu', 'https://www.vidu.com/'),
]
STYLE = ['Cinématique photoréaliste', 'Clip musical', 'Animation 3D', 'Fantastique', 'Vintage', 'Minimaliste']
RATIOS = {'Vertical 9:16': (360, 640), 'Horizontal 16:9': (640, 360), 'Carré 1:1': (512, 512)}
SCENE_SECONDS = 5.0

for key, value in {'scenes': [], 'clip': None, 'clip_error': '', 'project_id': None}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def ffmpeg_exists():
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def audio_duration(raw, suffix):
    if suffix == '.wav':
        try:
            import wave
            with wave.open(io.BytesIO(raw), 'rb') as wav:
                return wav.getnframes() / wav.getframerate()
        except Exception:
            pass
    if not ffmpeg_exists():
        return None
    with tempfile.TemporaryDirectory() as directory:
        p = Path(directory) / ('song' + suffix)
        p.write_bytes(raw)
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(p)], capture_output=True, text=True, timeout=30)
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None


def make_scenes(lyrics, seconds, style, ratio, idea):
    count = min(240, max(1, math.ceil(seconds / SCENE_SECONDS)))
    # Approximation only: without timestamps, lyrics cannot be synchronized to vocals.
    lines = [x.strip() for x in lyrics.splitlines() if x.strip() and not re.match(r'^\s*\[.*\]\s*$', x)]
    scenes = []
    for i in range(count):
        start = i * SCENE_SECONDS
        end = min(seconds, (i + 1) * SCENE_SECONDS)
        first = math.floor(i * len(lines) / count) if lines else 0
        last = max(first + 1, math.ceil((i + 1) * len(lines) / count)) if lines else 0
        excerpt = ' / '.join(lines[first:last]) if lines else idea
        prompt = (f'Professional {style.lower()} music video, {ratio}. '
                  f'Scene {i+1}, time {start:.1f}-{end:.1f} seconds. '
                  f'Visual narrative: {excerpt or idea or "cinematic journey"}. '
                  'One coherent 5-second shot, natural physical movement, clear camera direction, '
                  'consistent character identity, outfit, location and lighting. '
                  'No subtitles, no text, no watermark.')
        scenes.append({'start': start, 'end': end, 'lyrics': excerpt, 'prompt': prompt,
                       'video': None, 'image': None, 'last_frame': None, 'engine': None})
    return scenes


def last_frame(data, ext):
    if not ffmpeg_exists():
        return None
    with tempfile.TemporaryDirectory() as directory:
        src = Path(directory) / ('scene' + ext)
        dst = Path(directory) / 'last.png'
        src.write_bytes(data)
        result = subprocess.run(['ffmpeg', '-y', '-sseof', '-0.08', '-i', str(src), '-frames:v', '1', str(dst)],
                                capture_output=True, timeout=45)
        return dst.read_bytes() if result.returncode == 0 and dst.exists() else None


def assemble(scenes, music, music_ext, ratio):
    if not ffmpeg_exists():
        raise RuntimeError('FFmpeg/FFprobe sont requis pour assembler les scènes.')
    if not all(s['video'] for s in scenes):
        raise RuntimeError('Importe une vidéo pour chaque scène avant de lancer le montage.')
    w, h = RATIOS[ratio]
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        normalized = []
        for i, s in enumerate(scenes):
            data, ext = s['video']
            source = directory / f'source_{i}{ext}'
            output = directory / f'part_{i}.mp4'
            source.write_bytes(data)
            duration = max(0.1, s['end'] - s['start'])
            vf = (f'scale={w}:{h}:force_original_aspect_ratio=increase,'
                  f'crop={w}:{h},fps=24,setsar=1,format=yuv420p')
            cmd = ['ffmpeg', '-y', '-i', str(source), '-t', str(duration), '-an', '-vf', vf,
                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-movflags', '+faststart', str(output)]
            result = subprocess.run(cmd, capture_output=True, timeout=180)
            if result.returncode != 0:
                raise RuntimeError(f'Erreur vidéo scène {i+1}: {result.stderr.decode(errors="replace")[-350:]}')
            normalized.append(output)
        concat = directory / 'files.txt'
        concat.write_text(''.join(f"file '{p.as_posix()}'\n" for p in normalized), encoding='utf-8')
        silent = directory / 'silent.mp4'
        result = subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', str(silent)], capture_output=True, timeout=180)
        if result.returncode != 0:
            raise RuntimeError('Impossible de réunir les scènes vidéo.')
        if music:
            audio = directory / ('audio' + music_ext)
            audio.write_bytes(music)
            final = directory / 'clip_final.mp4'
            result = subprocess.run(['ffmpeg', '-y', '-i', str(silent), '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0',
                                     '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(final)],
                                    capture_output=True, timeout=180)
            if result.returncode != 0:
                raise RuntimeError('Impossible d’ajouter la musique au montage.')
            return final.read_bytes()
        return silent.read_bytes()


with st.container(border=True):
    st.subheader('1. Ta chanson')
    title = st.text_input('Titre du clip', value='Mon clip')
    artist = st.text_input('Artiste', value='KarManoX')
    lyrics = st.text_area('Paroles de la chanson (facultatives si tu décris ton idée)', height=180,
                          placeholder='Colle ici les paroles complètes…')
    idea = st.text_area('Idée / histoire du clip (facultatif)', height=75)
    music_file = st.file_uploader('Musique WAV ou MP3 (facultative)', type=['wav', 'mp3'])
    music = music_file.getvalue() if music_file else None
    music_ext = Path(music_file.name).suffix.lower() if music_file else ''
    duration_found = audio_duration(music, music_ext) if music else None
    if duration_found:
        st.success(f'Durée audio détectée : {duration_found:.1f} secondes')
    elif music:
        st.warning('Durée audio non détectée : renseigne la durée manuellement.')
    duration = st.number_input('Durée de la chanson en secondes (si audio absent ou non détecté)', min_value=5, max_value=1200, value=180, step=5)
    actual_duration = duration_found or float(duration)
    style = st.selectbox('Style visuel', STYLE)
    ratio = st.selectbox('Format vidéo', list(RATIOS))
    reference = st.file_uploader('Image de référence facultative', type=['png', 'jpg', 'jpeg', 'webp'])
    if reference:
        st.image(reference, width=200)
    if st.button('✨ Préparer toutes les scènes', type='primary', use_container_width=True):
        if not lyrics.strip() and not idea.strip():
            st.warning('Ajoute des paroles ou une idée.')
        else:
            st.session_state.scenes = make_scenes(lyrics, actual_duration, style, ratio, idea)
            st.session_state.clip = None
            st.success(f'{len(st.session_state.scenes)} scènes préparées.')

with st.container(border=True):
    st.subheader('2. Production et moteurs')
    automatic = st.checkbox('Activer la production automatique', value=False,
                            help='Désactivée par défaut. Aucun fournisseur externe n’est lancé sans intégration autorisée.')
    fallback = st.checkbox('Basculement automatique entre moteurs compatibles', value=True)
    continuity = st.checkbox('Continuité : reprendre la dernière image de la scène précédente', value=True)
    st.info('Lore Motion reste prioritaire. Les services externes sont accessibles manuellement. '
            'Le pilotage automatique de leurs sites n’est pas disponible sans API autorisée et vérifiée. '
            'Cocher Automatique ne contourne pas les quotas et ne lance pas les sites externes.')
    if automatic:
        st.warning('Aucun connecteur vidéo automatique compatible n’est configuré dans cette version. '
                   'Les scènes restent prêtes pour une intégration ultérieure.')
    st.caption('Ordre de priorité des services :')
    for name, url in SERVICES:
        st.link_button('↗ ' + name, url, use_container_width=True)

if st.session_state.scenes:
    scenes = st.session_state.scenes
    st.subheader(f'3. Storyboard — {len(scenes)} scènes')
    st.caption('Les paroles sont réparties approximativement. Sans transcription horodatée, ce n’est pas une synchronisation exacte avec le chant.')
    for i, scene in enumerate(scenes):
        with st.expander(f'Scène {i+1:02d} · {scene["start"]:.0f}–{scene["end"]:.0f} s' + (' · ✅ vidéo importée' if scene['video'] else ''), expanded=(i == 0)):
            st.caption('Paroles associées : ' + (scene['lyrics'] or '—'))
            scene['prompt'] = st.text_area('Prompt vidéo (modifiable)', value=scene['prompt'], key=f'prompt_{i}', height=145)
            st.code(scene['prompt'], language=None)
            if continuity and i > 0 and scenes[i-1]['last_frame']:
                st.image(scenes[i-1]['last_frame'], caption='Image de départ proposée : dernière image de la scène précédente', width=220)
                st.download_button('Télécharger cette image de raccord', scenes[i-1]['last_frame'], file_name=f'raccord_{i+1:02d}.png', mime='image/png', key=f'frame_{i}')
            elif reference and (i == 0 or not continuity):
                st.image(reference.getvalue(), caption='Image de référence', width=180)
            img = st.file_uploader('Image de départ de cette scène (facultative)', type=['png', 'jpg', 'jpeg', 'webp'], key=f'image_{i}')
            if img:
                scene['image'] = img.getvalue()
            if scene['image']:
                st.image(scene['image'], width=180)
            service_name = st.selectbox('Moteur utilisé', [x[0] for x in SERVICES], key=f'engine_{i}')
            scene['engine'] = service_name
            service_url = dict(SERVICES)[service_name]
            st.link_button('🌐 Ouvrir le moteur pour cette scène', service_url)
            video = st.file_uploader('Importer la vidéo MP4/WEBM générée', type=['mp4', 'webm'], key=f'video_{i}')
            if video:
                scene['video'] = (video.getvalue(), Path(video.name).suffix.lower())
                scene['last_frame'] = last_frame(*scene['video'])
            if scene['video']:
                st.video(scene['video'][0])
                if scene['last_frame']:
                    st.image(scene['last_frame'], caption='Dernière image extraite', width=180)
                elif not ffmpeg_exists():
                    st.caption('Extraction de la dernière image indisponible sans FFmpeg.')
    project = {'title': title, 'artist': artist, 'duration': actual_duration, 'style': style, 'ratio': ratio,
               'primary_service': 'Lore Motion', 'fallback_enabled': fallback, 'continuity_enabled': continuity,
               'scenes': [{k: v for k, v in s.items() if k not in ('video', 'image', 'last_frame')} for s in scenes]}
    st.download_button('📦 Télécharger le storyboard JSON', json.dumps(project, ensure_ascii=False, indent=2),
                       file_name='karmaclip_storyboard.json', mime='application/json', use_container_width=True)
    if st.button('🎞️ Assembler le clip MP4', type='primary', use_container_width=True):
        try:
            with st.spinner('Montage vidéo en cours…'):
                st.session_state.clip = assemble(scenes, music, music_ext, ratio)
            st.success('Clip final assemblé !')
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.clip:
        st.video(st.session_state.clip)
        st.download_button('⬇️ Télécharger le clip final', st.session_state.clip,
                           file_name='karmaclip_final.mp4', mime='video/mp4', use_container_width=True)
else:
    st.caption('Prépare le storyboard à l’étape 1 pour afficher les scènes.')

st.caption('Les services externes conservent leurs propres conditions, quotas et tarifs. Aucune génération illimitée n’est garantie.')
