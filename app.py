import io
import json
import os
import tempfile
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps

st.set_page_config(page_title='TikTok Movie Casting', page_icon='🎬', layout='wide')
st.title('🎬 TikTok Movie Casting')
st.caption('Idée → histoire → prompt → vidéo | Gratuit selon les quotas des services')

SERVICES = {
    'Wan AI': 'https://wan.video/',
    'LTX / Hugging Face': 'https://huggingface.co/spaces/Lightricks/ltx-video-distilled',
    'Kling AI': 'https://app.klingai.com/global/',
    'Vidu AI': 'https://www.vidu.com/',
}

RATIOS = {'TikTok 9:16': (360, 640), 'Cinéma 16:9': (640, 360), 'Carré 1:1': (512, 512)}
STYLES = ['Cinématique réaliste', 'Clip musical', 'Animation 3D', 'Fantastique', 'Science-fiction', 'Manga', 'Horreur', 'Vintage']
NEGATIVE = 'blurry, distorted, flickering, inconsistent motion, low quality, text, watermark'


def secret(name, default=''):
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def gemini(prompt):
    key = secret('GEMINI_API_KEY')
    if not key:
        raise RuntimeError('Clé Gemini absente : utilise le prompt manuel ci-dessous.')
    models = list(dict.fromkeys([secret('GEMINI_MODEL', 'gemini-2.5-flash').replace('models/', ''), 'gemini-2.5-flash-lite']))
    errors = []
    for model in models:
        try:
            r = requests.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 1800}},
                timeout=(4, 12),
            )
            if r.status_code in (401, 403):
                raise RuntimeError('Clé Gemini refusée.')
            if r.status_code == 429:
                errors.append('Quota Gemini atteint')
                continue
            r.raise_for_status()
            chunks = [p['text'] for c in r.json().get('candidates', []) for p in c.get('content', {}).get('parts', []) if p.get('text')]
            if chunks:
                return '\n'.join(chunks).strip()
            errors.append(f'{model}: aucune réponse textuelle')
        except (requests.RequestException, ValueError) as exc:
            errors.append(f'{model}: {str(exc)[:120]}')
    raise RuntimeError('; '.join(errors) or 'Gemini indisponible')


def locate_video(obj):
    if isinstance(obj, (str, Path)):
        v = str(obj)
        return v if v.lower().split('?')[0].endswith(('.mp4', '.webm')) else None
    if isinstance(obj, dict):
        for item in obj.values():
            found = locate_video(item)
            if found:
                return found
    if isinstance(obj, (tuple, list)):
        for item in obj:
            found = locate_video(item)
            if found:
                return found
    return None


def ltx_video(prompt, image_bytes, image_name, ratio, duration):
    from gradio_client import Client, handle_file
    # La signature de l'API publique du Space peut changer : erreur affichée sans masquer l'échec.
    if ratio == 'TikTok 9:16':
        h, w = 704, 384
    elif ratio == 'Cinéma 16:9':
        h, w = 384, 704
    else:
        h, w = 512, 512
    tmp = None
    try:
        mode = 'text-to-video'
        api = '/text_to_video'
        image_arg = None
        if image_bytes:
            suffix = Path(image_name).suffix.lower()
            if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
                suffix = '.png'
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(image_bytes)
                tmp = f.name
            image_arg = handle_file(tmp)
            mode = 'image-to-video'
            api = '/image_to_video'
        token = secret('HF_TOKEN')
        client = Client('Lightricks/ltx-video-distilled', token=token or None, verbose=False)
        result = client.predict(prompt, NEGATIVE, image_arg, None, h, w, mode, float(duration), 9, 42, True, 3.0, False, api_name=api)
        path = locate_video(result)
        if not path:
            raise RuntimeError('Le générateur n’a renvoyé aucun fichier vidéo.')
        ext = '.webm' if path.lower().split('?')[0].endswith('.webm') else '.mp4'
        if path.startswith(('https://', 'http://')):
            with requests.get(path, timeout=120, stream=True) as r:
                r.raise_for_status()
                parts, total = [], 0
                for chunk in r.iter_content(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise RuntimeError('Vidéo trop volumineuse (100 Mo maximum).')
                    parts.append(chunk)
                return b''.join(parts), ext
        p = Path(path)
        if p.stat().st_size > 100 * 1024 * 1024:
            raise RuntimeError('Vidéo trop volumineuse (100 Mo maximum).')
        return p.read_bytes(), ext
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def animate_images(images, ratio, seconds=4, motion='Zoom avant'):
    import numpy as np
    import imageio.v2 as imageio
    w, h = RATIOS[ratio]
    fps = 16
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        path = f.name
    try:
        writer = imageio.get_writer(path, fps=fps, codec='libx264', quality=7, macro_block_size=2, ffmpeg_log_level='error')
        try:
            for raw in images:
                with Image.open(io.BytesIO(raw)) as im:
                    source = ImageOps.exif_transpose(im).convert('RGB')
                base = ImageOps.fit(source, (round(w * 1.2), round(h * 1.2)), method=Image.Resampling.LANCZOS)
                for frame in range(seconds * fps):
                    t = frame / max(1, seconds * fps - 1)
                    if motion == 'Travelling horizontal':
                        current = base
                        x = round((current.width - w) * t)
                    else:
                        factor = (1 + 0.12 * t) if motion == 'Zoom avant' else (1.12 - 0.12 * t)
                        current = base.resize((round(base.width * factor), round(base.height * factor)), Image.Resampling.BICUBIC)
                        x = (current.width - w) // 2
                    y = (current.height - h) // 2
                    writer.append_data(np.asarray(current.crop((x, y, x + w, y + h))))
        finally:
            writer.close()
        return Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)


def font(size):
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def poster(raw, title, artist, ratio):
    w, h = RATIOS[ratio]
    with Image.open(io.BytesIO(raw)) as im:
        image = ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'), (w * 2, h * 2), method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image, 'RGBA')
    draw.rectangle((0, round(h * 1.5), w * 2, h * 2), fill=(0, 0, 0, 180))
    for label, y, size in [(title[:55], 1.7, max(20, w // 8)), (artist[:55], 1.87, max(15, w // 14))]:
        if not label:
            continue
        f = font(size)
        while size > 15 and draw.textbbox((0, 0), label, font=f)[2] > w * 1.85:
            size -= 2
            f = font(size)
        draw.text((w, round(h * y)), label, fill='white', font=f, anchor='mm')
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


for k, v in {'story': '', 'video_prompt': '', 'analysis': '', 'scenarios': '', 'video_bytes': None, 'video_ext': '.mp4', 'poster_bytes': None, 'last_error': ''}.items():
    if k not in st.session_state:
        st.session_state[k] = v

with st.container(border=True):
    st.subheader('1. Ton idée')
    keywords = st.text_input('Écris 3 ou 4 mots', placeholder='Ex. tigre, liberté, nuit, danse')
    title = st.text_input('Titre (facultatif)', value='Mon clip')
    style = st.selectbox('Style', STYLES)
    ratio = st.selectbox('Format', list(RATIOS))
    reference = st.file_uploader('Image de référence (facultative)', type=['png', 'jpg', 'jpeg', 'webp'])
    image_bytes = reference.getvalue() if reference else None
    if image_bytes and len(image_bytes) > 10 * 1024 * 1024:
        st.error('Image supérieure à 10 Mo.')
        image_bytes = None
    if image_bytes:
        st.image(image_bytes, caption='Image de référence', width=250)

base_prompt = f'''Create one coherent cinematic 5-second video shot, {style}, {ratio}.
Story keywords: {keywords or 'a surprising cinematic journey'}.
One continuous camera move, natural detailed subject movement, consistent face and character identity, clear beginning and ending, beautiful lighting, professional music-video cinematography. No captions, no lettering, no logos.'''

with st.container(border=True):
    st.subheader('2. Histoire et prompt')
    if st.button('✨ Créer automatiquement une histoire', type='primary', use_container_width=True):
        if not keywords.strip():
            st.warning('Écris quelques mots pour commencer.')
        else:
            instruction = f'''Écris en français une histoire visuelle originale et concise (80 à 130 mots) à partir de ces mots : {keywords}. Style : {style}. Puis écris sous le titre VIDEO PROMPT un seul prompt anglais précis pour une vidéo IA de 5 secondes, plan unique, mouvement réel des personnages, continuité visuelle, sans texte à l’écran. Évite les clichés.'''
            try:
                with st.spinner('Création de l’histoire...'):
                    st.session_state.story = gemini(instruction)
                st.session_state.video_prompt = base_prompt + '\nStory: ' + st.session_state.story[:1000]
                st.success('Histoire créée.')
            except Exception as exc:
                st.info(f'Gemini indisponible ({str(exc)[:160]}). Histoire et prompt créés localement, sans attendre davantage.')
                st.session_state.story = (
                    f'{title}. {keywords.strip().capitalize()}. '
                    f'Une scène {style.lower()} prend vie dans un plan continu. '
                    'La caméra découvre le sujet, suit un mouvement naturel puis révèle '
                    'un détail inattendu qui relie les éléments de départ. '
                    'La lumière et le rythme évoluent progressivement jusqu’à une image finale marquante.'
                )
                st.session_state.video_prompt = base_prompt
    st.session_state.story = st.text_area('Ton histoire (modifiable)', value=st.session_state.story, height=145)
    st.session_state.video_prompt = st.text_area('Prompt vidéo (modifiable)', value=st.session_state.video_prompt or base_prompt, height=165)
    st.caption('Pour copier sur Android : appui long sur le prompt, puis Copier.')

with st.container(border=True):
    st.subheader('3. Générer la vidéo')
    mode = st.radio('Choix du générateur', ['Automatique', 'Manuel'], horizontal=True)
    st.caption('Automatique : tentative LTX si son API est disponible. En cas d’échec, secours MP4 animé uniquement si une image est fournie. Wan, Kling et Vidu sont proposés en mode manuel tant que leurs interfaces gratuites ne donnent pas accès à une API vérifiée. Aucune API payante n’est appelée.')
    duration = st.slider('Durée IA (secondes)', 2.0, 8.0, 5.0, 0.5)
    choice = st.selectbox('Générateur manuel', list(SERVICES)) if mode == 'Manuel' else None
    if choice:
        st.link_button(f'🌐 Ouvrir {choice}', SERVICES[choice], use_container_width=True)
        st.info('Copie le prompt ci-dessus et colle-le sur ce service. Les limites gratuites varient selon le compte et le fournisseur.')
    if st.button('🎥 Lancer la génération', type='primary', use_container_width=True):
        st.session_state.last_error = ''
        if not keywords.strip() and not st.session_state.video_prompt.strip():
            st.warning('Saisis ton idée.')
        elif mode == 'Manuel' and choice != 'LTX / Hugging Face':
            st.info(f'Ouvre {choice} avec le bouton ci-dessus pour lancer la génération manuelle. Aucun prélèvement automatique n’est effectué par cette application.')
        else:
            st.session_state.video_bytes = None
            st.session_state.last_error = ''
            try:
                with st.spinner('Tentative de génération IA LTX...'):
                    data, ext = ltx_video(st.session_state.video_prompt or base_prompt, image_bytes, reference.name if reference else '', ratio, duration)
                st.session_state.video_bytes, st.session_state.video_ext = data, ext
                st.success('Vidéo IA générée !')
            except Exception as exc:
                st.session_state.last_error = str(exc)[:400]
                st.warning('LTX indisponible : ' + st.session_state.last_error)
                if mode == 'Automatique' and image_bytes:
                    try:
                        with st.spinner('Création du MP4 de secours...'):
                            st.session_state.video_bytes = animate_images([image_bytes], ratio)
                            st.session_state.video_ext = '.mp4'
                        st.success('MP4 animé de secours créé (mouvement de caméra, pas de gestes IA).')
                    except Exception as fallback_exc:
                        st.error('Secours MP4 impossible : ' + str(fallback_exc)[:250])
                elif mode == 'Automatique':
                    st.info('Ajoute une image pour obtenir un MP4 animé de secours, ou utilise un générateur manuel.')
    # Accès directs disponibles même après un échec API ou un quota épuisé.
    if st.session_state.last_error:
        st.info('La génération automatique est indisponible pour le moment. Choisis un site ci-dessous et colle le prompt vidéo préparé.')
    st.markdown('#### 🌐 Générateurs vidéo — accès direct')
    st.caption('Ces boutons ouvrent les sites. Ils ne déclenchent ni abonnement ni paiement. Vérifie le quota gratuit proposé sur ton compte avant de lancer une génération.')
    col1, col2 = st.columns(2)
    for idx, (service_name, service_url) in enumerate(SERVICES.items()):
        with (col1 if idx % 2 == 0 else col2):
            st.link_button('↗ ' + service_name, service_url, use_container_width=True)
    st.code(st.session_state.video_prompt or base_prompt, language=None)
    st.caption('Copie ce prompt pour le coller dans Wan, LTX, Kling ou Vidu.')
    if st.session_state.video_bytes:
        st.video(st.session_state.video_bytes)
        ext = st.session_state.video_ext
        st.download_button('⬇️ Télécharger ma vidéo', st.session_state.video_bytes, file_name='mon_clip' + ext, mime='video/webm' if ext == '.webm' else 'video/mp4', use_container_width=True)

with st.expander('🎞️ Clip MP4 gratuit à partir de plusieurs images'):
    pictures = st.file_uploader('Images du clip', type=['png', 'jpg', 'jpeg', 'webp'], accept_multiple_files=True, key='slideshow')
    sec = st.slider('Secondes par image', 2, 8, 4)
    motion = st.selectbox('Mouvement', ['Zoom avant', 'Zoom arrière', 'Travelling horizontal'])
    if st.button('Créer le clip MP4', use_container_width=True):
        if not pictures:
            st.warning('Ajoute au moins une image.')
        elif len(pictures) > 20:
            st.warning('Maximum 20 images.')
        else:
            try:
                with st.spinner('Encodage du MP4...'):
                    st.session_state.video_bytes = animate_images([p.getvalue() for p in pictures], ratio, sec, 'Zoom arriere' if motion == 'Zoom arrière' else motion)
                    st.session_state.video_ext = '.mp4'
                st.success('Clip créé. Télécharge-le dans la section vidéo ci-dessus.')
                st.rerun()
            except Exception as exc:
                st.error(str(exc)[:300])

with st.expander('🎨 Affiche de film ou pochette'):
    st.caption('Sans abonnement : crée une image dans Bing, puis importe-la ici pour ajouter le titre.')
    st.code(f'Professional {style} movie poster, story: {st.session_state.story or keywords}, {ratio}, detailed cinematic lighting, no text, no watermark', language='text')
    st.link_button('Ouvrir Bing Image Creator', 'https://www.bing.com/images/create')
    poster_upload = st.file_uploader('Importer une image', type=['png', 'jpg', 'jpeg', 'webp'], key='poster')
    artist = st.text_input('Nom de l’artiste', value='KarManoX')
    if st.button('Finaliser mon affiche') and poster_upload:
        try:
            st.session_state.poster_bytes = poster(poster_upload.getvalue(), title, artist, ratio)
        except Exception as exc:
            st.error(str(exc)[:200])
    if st.session_state.poster_bytes:
        st.image(st.session_state.poster_bytes, width=300)
        st.download_button('⬇️ Télécharger mon affiche', st.session_state.poster_bytes, file_name='affiche.png', mime='image/png')

with st.expander('📦 Exporter le projet'):
    data = {'titre': title, 'mots': keywords, 'style': style, 'format': ratio, 'histoire': st.session_state.story, 'prompt_video': st.session_state.video_prompt}
    st.download_button('Télécharger le projet JSON', json.dumps(data, ensure_ascii=False, indent=2), file_name='projet.json', mime='application/json')
    st.download_button('Télécharger le prompt TXT', st.session_state.video_prompt or base_prompt, file_name='prompt_video.txt')

st.caption('Aucun abonnement ni achat automatique. Les quotas et conditions des services externes restent applicables.')
