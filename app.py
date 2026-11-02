import json
import random
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

st.set_page_config(page_title='KarManoX Video', page_icon='🎬', layout='centered')
st.markdown('''<style>.block-container{max-width:760px;padding-top:1.2rem}div.stButton>button[kind="primary"]{font-weight:750}h1{letter-spacing:-.04em}</style>''', unsafe_allow_html=True)

STYLES = {
    'Rock énergique': 'energetic rock concert mood, joyful facial expression, rhythmic head and shoulder movements',
    'Cinéma réaliste': 'cinematic photorealism, natural body motion, detailed lighting, smooth camera tracking',
    'Clip musical': 'professional music video, dynamic performance, rhythmic motion, engaging framing',
    'Doux et naturel': 'subtle realistic movement, natural smiles, soft lighting, gentle camera movement',
    'Fantastique': 'magical cinematic atmosphere, fluid movement, imaginative lighting',
}
VARIATIONS = [
    'Single continuous shot, natural and believable movements, steady face identity.',
    'Camera gently pushes in, fluid realistic motion, authentic expression.',
    'Energetic close-up with expressive movements, no abrupt cuts.',
    'Natural cinematic movement, strong visual continuity, stable composition.',
    'Subtle handheld camera feel, lifelike motion and convincing gestures.',
]
NEGATIVE = 'No text, no subtitles, no watermarks, no distorted hands, no extra fingers, no face morphing, no flicker.'

for key, default in {'prompt':'', 'idea':'', 'variant':-1, 'video':None, 'logs':[], 'busy':False, 'last_signature':None}.items():
    st.session_state.setdefault(key, default)


def make_prompt(idea, style, variation, has_image):
    prefix = ('Animate the person or scene from the reference image. Preserve the original identity, face, clothing and background. '
              if has_image else 'Create a short original video scene. ')
    return f'{prefix}{idea.strip().rstrip(".")}. {STYLES[style]}. {VARIATIONS[variation % len(VARIATIONS)]} {NEGATIVE}'


def load_providers():
    try:
        raw = st.secrets.get('providers_json', '[]')
        providers = json.loads(raw) if isinstance(raw, str) else list(raw)
        # A provider must be explicitly approved as free and use a Gradio endpoint.
        return [p for p in providers if p.get('enabled') is True and p.get('free_only') is True and p.get('space') and p.get('api_name') and p.get('image_param') and p.get('prompt_param')]
    except Exception:
        return []


def video_path(value):
    if isinstance(value, dict):
        for key in ('video', 'path', 'name', 'url', 'value', 'data', 'output'):
            if key in value:
                found = video_path(value[key])
                if found:
                    return found
        for v in value.values():
            found = video_path(v)
            if found:
                return found
    if isinstance(value, (tuple, list)):
        for v in value:
            found = video_path(v)
            if found:
                return found
    if isinstance(value, str) and urlparse(value.split('?')[0]).path.lower().endswith(('.mp4', '.webm')):
        return value
    return None


def run_provider(p, photo_path, prompt, seconds):
    from gradio_client import Client, handle_file
    client = Client(p['space'], verbose=False)
    kwargs = {p['prompt_param']: prompt}
    if photo_path:
        kwargs[p['image_param']] = handle_file(str(photo_path))
    elif not p.get('supports_text_to_video', False):
        raise ValueError('Ce moteur exige une photo')
    if p.get('duration_param'):
        kwargs[p['duration_param']] = seconds
    kwargs.update(p.get('fixed_params', {}))
    job = client.submit(api_name=p['api_name'], **kwargs)
    deadline = time.monotonic() + int(p.get('timeout_seconds', 240))
    while not job.done():
        if time.monotonic() > deadline:
            # Cancel only if safe; timeout does not guarantee backend job stopped.
            try: job.cancel()
            except Exception: pass
            raise TimeoutError('Délai dépassé (génération distante éventuellement encore active)')
        time.sleep(2)
    result = job.result()
    path = video_path(result)
    if not path:
        raise ValueError('Le fournisseur n’a pas retourné de MP4/WebM identifiable')
    if path.startswith('https://'):
        import requests
        host = urlparse(path).hostname or ''
        if not (host.endswith('.hf.space') or host.endswith('.huggingface.co')):
            raise ValueError('URL vidéo non approuvée')
        response = requests.get(path, timeout=45, stream=True)
        response.raise_for_status()
        out = Path(tempfile.mkstemp(suffix='.mp4')[1])
        with out.open('wb') as f:
            total = 0
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > 150_000_000:
                    raise ValueError('Vidéo trop volumineuse')
                f.write(chunk)
        return out.read_bytes()
    local = Path(path)
    if not local.is_file() or local.stat().st_size > 150_000_000:
        raise ValueError('Fichier vidéo absent ou trop volumineux')
    return local.read_bytes()


st.title('🎬 KarManoX Video')
st.caption('Une photo (facultative) · une idée · une vidéo — sur la même page')
photo = st.file_uploader('1 · Ajoute une photo (facultatif)', type=['jpg','jpeg','png','webp'], help='Pour animer un visage ou une photo existante. Sans photo, il faut un moteur texte-vers-vidéo.')
if photo:
    st.image(photo, caption='Photo de départ', width=250)

idea = st.text_area('2 · Explique ce que tu veux voir', key='idea', height=105, placeholder='Ex. Il sourit, lève le bras, fait le signe rock et tire la langue au rythme de la musique.')
style = st.selectbox('Ambiance', list(STYLES), index=0)
col1, col2 = st.columns(2)
with col1:
    if st.button('✨ Créer le prompt', use_container_width=True, disabled=not idea.strip()):
        st.session_state.variant = 0
        st.session_state.prompt = make_prompt(idea, style, 0, bool(photo))
with col2:
    if st.button('🔄 Autre proposition', use_container_width=True, disabled=not idea.strip()):
        st.session_state.variant = (st.session_state.variant + 1) % len(VARIATIONS)
        st.session_state.prompt = make_prompt(idea, style, st.session_state.variant, bool(photo))

st.text_area('3 · Prompt modifiable (tu peux le garder ou le changer)', key='prompt', height=185)
seconds = st.select_slider('Durée souhaitée', options=[2,3,4,5], value=3)
providers = load_providers()
with st.expander('⚙️ Moteurs gratuits et fonctionnement'):
    if providers:
        st.success(f'{len(providers)} moteur(s) configuré(s), disponibilité non garantie')
        for p in providers:
            st.write('•', p.get('name', p['space']))
    else:
        st.warning('Aucun moteur gratuit connecté. Le générateur de prompts fonctionne déjà, mais pas encore la création vidéo.')
    st.caption('La bascule est automatique entre les API configurées et autorisées. Les quotas partagés ne sont pas contournés. Aucun service payant n’est appelé.')

if st.button('🎥 GÉNÉRER LA VIDÉO', type='primary', use_container_width=True, disabled=not st.session_state.prompt.strip() or not providers):
    st.session_state.video = None
    st.session_state.logs = []
    if not photo and not any(p.get('supports_text_to_video') for p in providers):
        st.error('Ajoute une photo : les moteurs configurés ne prennent pas en charge le texte seul.')
    else:
        with st.spinner('Génération en cours. En cas d’erreur, essai du moteur suivant…'):
            path = None
            try:
                if photo:
                    suffix = '.' + photo.name.rsplit('.', 1)[-1].lower()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(photo.getvalue())
                        path = Path(tmp.name)
                for p in providers:
                    if not photo and not p.get('supports_text_to_video'):
                        continue
                    name = p.get('name', p['space'])
                    try:
                        st.session_state.video = run_provider(p, path, st.session_state.prompt, seconds)
                        st.session_state.logs.append(f'✅ {name} : vidéo générée')
                        break
                    except Exception as exc:
                        msg = str(exc).replace('\n', ' ')[:220]
                        st.session_state.logs.append(f'⚠️ {name} : {msg}')
            finally:
                if path:
                    path.unlink(missing_ok=True)
        if st.session_state.video is None:
            st.error('Aucun moteur configuré n’a réussi. La photo et le prompt restent sur cette page.')

if st.session_state.video:
    st.success('Vidéo prête !')
    st.video(st.session_state.video)
    st.download_button('⬇️ Enregistrer la vidéo sur mon téléphone', data=st.session_state.video, file_name='KarManoX_video.mp4', mime='video/mp4', use_container_width=True)
if st.session_state.logs:
    with st.expander('Détails des tentatives'):
        for log in st.session_state.logs:
            st.write(log)
