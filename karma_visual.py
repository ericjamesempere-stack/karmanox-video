"""KarmaClip: independent visual brief and cover workshop (no paid API)."""
import io
import subprocess
import tempfile
from pathlib import Path
import streamlit as st
from PIL import Image, ImageOps, ImageDraw, ImageFont

STYLES = ['Cinématographique', 'Photographique', 'Illustration', 'Anime / manga', 'Surréaliste', 'Minimaliste']

def _crop(im, size):
    return ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'), size, method=Image.Resampling.LANCZOS)

def _audio_info(data, suffix):
    if len(data) > 100 * 1024 * 1024:
        return 'Fichier supérieur à 100 Mo : analyse ignorée.'
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / ('audio' + suffix)
        f.write_bytes(data)
        try:
            r = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:format_tags=artist,title','-of','default=noprint_wrappers=1',str(f)],capture_output=True,text=True,timeout=15)
            return r.stdout.strip() if r.returncode == 0 else 'Métadonnées non disponibles.'
        except (OSError,subprocess.TimeoutExpired):
            return 'ffprobe indisponible : analyse audio non effectuée.'

def render():
    st.header('🎨 1 · Studio image et musique')
    purpose = st.radio('Créer pour', ['Clip vidéo (9:16)', 'Pochette de single (1:1)'], horizontal=True, key='kv_purpose')
    subject = st.text_area('Description visuelle (facultative)',key='kv_description',placeholder='Un tigre dans la brume, regard intense…')
    lyrics = st.text_area('Paroles (facultatives)',key='kv_lyrics',height=130)
    audio = st.file_uploader('Musique MP3 / WAV / M4A (facultative)',type=['mp3','wav','m4a'],key='kv_audio')
    reference = st.file_uploader('Photo de référence (facultative)',type=['png','jpg','jpeg','webp'],key='kv_reference')
    style = st.selectbox('Style', STYLES,key='kv_style')
    title = st.text_input('Titre du single (facultatif)',key='kv_title')
    artist = st.text_input('Nom de l’artiste (facultatif)',key='kv_artist')
    if audio:
        st.caption('Analyse technique de la musique (pas de reconnaissance automatique du genre ou des émotions) :')
        st.code(_audio_info(audio.getvalue(),Path(audio.name).suffix.lower()))
    ratio = '9:16, vertical, 1080x1920' if purpose.startswith('Clip') else '1:1, square, 3000x3000'
    first_lines = lyrics.strip().splitlines()[:5]
    cues = ' / '.join(line.strip() for line in first_lines if line.strip())[:420]
    prompt = ('Create an original '+style.lower()+' visual for a '+('music video opening frame' if purpose.startswith('Clip') else 'music single cover')+'. '
              +'Composition: '+ratio+'. '
              +(('Visual direction: '+subject.strip()+'. ') if subject.strip() else '')
              +(('Lyrical inspiration (interpret visually, do not print lyrics): '+cues+'. ') if cues else '')
              +'Clear focal subject, intentional composition, consistent identity, high quality. '
              +('No lettering unless added separately.' if not purpose.startswith('Clip') else 'Stable composition suitable as the first frame of an image-to-video clip.'))
    st.text_area('Prompt image prêt à copier',value=prompt,height=175,key='kv_prompt_preview')
    st.download_button('⬇️ Télécharger le prompt image',prompt.encode('utf-8'),'KarmaClip_prompt_image.txt','text/plain',use_container_width=True)
    st.info('Le prompt est créé localement. La génération d’une image IA nécessite un moteur d’image connecté ; aucun résultat IA n’est simulé.')
    if reference:
        try:
            if reference.size > 25*1024*1024:
                raise ValueError('Image supérieure à 25 Mo')
            im = Image.open(io.BytesIO(reference.getvalue()))
            size = (1080,1920) if purpose.startswith('Clip') else (3000,3000)
            out = _crop(im,size)
            if not purpose.startswith('Clip') and (title or artist):
                d=ImageDraw.Draw(out)
                # Text overlay on a user-supplied image; this is a layout tool, not AI image generation.
                font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
                font=ImageFont.truetype(font_path,110) if Path(font_path).exists() else ImageFont.load_default()
                small=ImageFont.truetype(font_path,66) if Path(font_path).exists() else ImageFont.load_default()
                if title:
                    d.text((130,2500),title[:38],fill='white',font=font,stroke_width=5,stroke_fill='black')
                if artist:
                    d.text((130,2680),artist[:45],fill='white',font=small,stroke_width=4,stroke_fill='black')
            b=io.BytesIO();out.save(b,format='PNG');raw=b.getvalue()
            st.image(raw,caption='Visuel cadré à partir de ta photo (sans génération IA)',width=260)
            st.download_button('⬇️ Télécharger le visuel PNG',raw,'KarmaClip_visuel.png','image/png',use_container_width=True)
            if purpose.startswith('Clip'):
                st.session_state['kv_video_start_image']=raw
                st.success('Image prête à servir de référence au clip ci-dessous.')
        except Exception as exc:
            st.error('Impossible de préparer le visuel : '+str(exc))
    st.divider()
