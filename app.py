"""KarmaClip Studio — interface simple, compatible avec requirements.txt existant.
LoreMotion: workflow manuel tant qu'aucune intégration serveur authentifiée n'est disponible.
Wan: tentative réelle via le module wan_nifty existant, disponibilité non garantie.
"""
import io
import re
import json
import zipfile
import streamlit as st
from PIL import Image, ImageOps

st.set_page_config(page_title='KarmaClip Studio', page_icon='🎬', layout='centered')
st.title('🎬 KarmaClip Studio')
st.caption('Une photo · une idée · une vidéo — version simplifiée')


def normalize(upload):
    if upload.size > 25 * 1024 * 1024:
        raise ValueError('Image supérieure à 25 Mo. Essaie une version plus légère.')
    with Image.open(io.BytesIO(upload.getvalue())) as original:
        img = ImageOps.exif_transpose(original)
        img.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            rgba = img.convert('RGBA')
            background = Image.new('RGB', rgba.size, 'white')
            background.paste(rgba, mask=rgba.getchannel('A'))
            img = background
        else:
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, 'PNG', optimize=True)
        return buf.getvalue()


def scenes_from_text(text, count, identity):
    # Découpage local déterministe, pas une analyse IA de l'image ou du morceau.
    lines = [s.strip() for s in re.split(r'\n+|(?<=[.!?])\s+', text) if s.strip()]
    if not lines:
        lines = ['Le personnage avance et regarde la caméra.']
    result = []
    for i in range(count):
        phrase = lines[min(len(lines)-1, i * len(lines) // count)]
        prompt = (f'Scene {i+1}: {phrase}. One clear continuous movement. '
                  'Keep the same character identity, face, outfit, and original visual style. '
                  'Smooth natural motion, stable camera, no captions, vertical 9:16.')
        if identity:
            prompt += ' Reference image is the starting frame.'
        result.append(prompt)
    return result

st.subheader('1 · Photo')
photo = st.file_uploader('Choisir une image', type=['jpg', 'jpeg', 'png', 'webp'], key='kc_photo')
photo_bytes = None
if photo:
    try:
        photo_bytes = normalize(photo)
        st.success('Photo reçue : ' + photo.name)
        st.image(photo_bytes, width=280)
    except Exception as exc:
        st.error('Impossible de lire cette photo : ' + str(exc))

st.subheader('2 · Mouvement ou paroles')
idea = st.text_area('Décris la vidéo', placeholder='Deux personnages dansent puis se prennent la main…', height=115)
music = st.file_uploader('Musique (facultative)', type=['mp3', 'wav', 'm4a'], key='kc_audio')
if music:
    st.caption(f'Musique reçue : {music.name} ({music.size / (1024*1024):.1f} Mo). Elle sert de référence, pas de synchronisation automatique dans cette version.')

st.subheader('3 · Génération')
engine = st.radio('Moteur', ['LoreMotion (prioritaire)', 'Wan 2.2 (essai direct)'], horizontal=False)
count = st.slider('Nombre de scènes', 1, 30, 1)
if 'kc_prompts' not in st.session_state:
    st.session_state.kc_prompts = []
if st.button('Préparer mes scènes', type='primary', use_container_width=True):
    st.session_state.kc_prompts = scenes_from_text(idea.strip(), count, bool(photo_bytes))
if st.session_state.kc_prompts:
    st.subheader('Scènes préparées')
    for i, p in enumerate(st.session_state.kc_prompts, 1):
        with st.expander(f'Scène {i}', expanded=i == 1):
            st.code(p, language=None)
    st.download_button('⬇️ Télécharger les prompts', '\n\n'.join(st.session_state.kc_prompts), 'KarmaClip_prompts.txt', 'text/plain', use_container_width=True)

if engine.startswith('LoreMotion'):
    st.info('LoreMotion est prioritaire. Son automatisation nécessite une session navigateur authentifiée côté serveur ; elle n’est pas installée ici. Aucun faux bouton « Générer » : prépare le prompt puis ouvre LoreMotion.')
    st.link_button('🎥 Ouvrir LoreMotion', 'https://loremotion.com/', use_container_width=True)
    if photo_bytes:
        st.download_button('⬇️ Photo prête pour LoreMotion', photo_bytes, 'KarmaClip_image.png', 'image/png', use_container_width=True)
else:
    st.caption('Wan utilise la démonstration GPU publique du module wan_nifty.py. Elle peut être indisponible.')
    if st.button('🎬 Lancer Wan 2.2', use_container_width=True):
        if not photo_bytes:
            st.warning('Ajoute une photo.')
        elif not idea.strip():
            st.warning('Ajoute un mouvement.')
        else:
            try:
                from wan_nifty import generate
                with st.spinner('Génération Wan en cours…'):
                    video = generate(photo_bytes, 'karmaclip.png', scenes_from_text(idea, 1, True)[0])
                if not video or len(video) < 1024:
                    raise RuntimeError('Aucun fichier vidéo valide reçu.')
                st.session_state.kc_video = video
                st.success('Vidéo reçue !')
            except Exception as exc:
                st.error('Wan indisponible ou génération échouée : ' + str(exc))
    if st.session_state.get('kc_video'):
        st.video(st.session_state.kc_video)
        st.download_button('⬇️ Télécharger le MP4', st.session_state.kc_video, 'KarmaClip.mp4', 'video/mp4', use_container_width=True)

st.divider()
st.caption('Limites : pas de génération automatique LoreMotion, pas de création IA de corps depuis une tête, pas de montage musical automatique. Ces fonctions nécessitent des services de calcul et une intégration vérifiée.')
