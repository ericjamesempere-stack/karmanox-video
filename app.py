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

# Nouveau projet : effacer les saisies, fichiers et résultats de la session.
# Ne supprime aucun fichier sur GitHub ni aucun projet exporté par l'utilisateur.
if st.button('🧹 Nouveau projet — vider tous les champs', key='kc_clear_all', use_container_width=True):
    for _key in list(st.session_state.keys()):
        if _key != 'kc_clear_all':
            del st.session_state[_key]
    st.rerun()


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


def scenes_from_text(text, count, identity, people=2, action='Libre', locked=True):
    """Prompts de continuité explicites, sans prétendre analyser l'image."""
    lines = [v.strip() for v in re.split(r'\n+|(?<=[.!?])\s+', text) if v.strip()]
    if not lines:
        lines = ['Subtle natural movement, keeping the original composition.']
    n = {1: 'exactly ONE original person', 2: 'exactly TWO original people',
         3: 'exactly THREE original people'}.get(people, 'exactly the original people')
    common = (
        'IMAGE-TO-VIDEO. The uploaded reference image is the literal FIRST FRAME, '
        'not a visual inspiration. Animate the SAME existing subjects, never generate replacement subjects. '
        f'There must be {n} visible throughout, except when an original person naturally exits the frame. '
        'Each person has one persistent physical body and one persistent face. '
        'Preserve the exact original faces, hairstyles, clothes, body proportions, artistic medium, '
        'lighting, furniture, background, and relative positions. '
        'One continuous shot, fixed camera, no cuts, no sudden appearances. '
        'Motion must begin at the exact pose and location shown in the reference. '
        'If a person stands up, their ORIGINAL seated body rises smoothly, leaving their seat empty. '
        'Never add a standing copy beside a seated original. '
    )
    negative = (
        'NEGATIVE: duplicate person, twin, cloned woman, cloned man, extra limbs, '
        'extra people, character spawning, replacement body, teleportation, morphing, '
        'identity swap, costume change, scene cut, camera jump, new background, text, watermark.'
    )
    specific = {
        'Femme assise se lève': (
            'The ORIGINAL woman already seated in the reference slowly stands from HER OWN seat. '
            'Her hips lift from the cushion, knees extend, feet stay grounded, and her original seat becomes EMPTY. '
            'The original man remains seated with only a subtle head movement. '
            'At every instant there is exactly one woman and one man.'),
        'Homme assis se lève': (
            'The ORIGINAL man already seated in the reference slowly stands from HIS OWN seat. '
            'His hips lift from the cushion, knees extend, feet stay grounded, and his original seat becomes EMPTY. '
            'The original woman remains seated with only a subtle head movement. '
            'At every instant there is exactly one man and one woman.'),
        'Les deux restent assis': (
            'Both ORIGINAL people remain seated in their existing seats throughout. '
            'Only small natural head and hand movements, with no one standing up.'),
        'Libre': ''
    }
    prompts = []
    for i in range(count):
        instruction = lines[min(len(lines)-1, i * len(lines) // count)]
        movement = specific[action] if action != 'Libre' and i == 0 else instruction
        if identity and locked:
            prompt = (f'SCENE {i+1}. ' + common + 'ACTION: ' + movement +
                      ' Only this single physical action during this shot. '
                      'Keep all other people and objects stable. ' + negative)
        else:
            prompt = (f'SCENE {i+1}. ACTION: {movement}. Single continuous action, '
                      'preserve original identities, fixed camera, no extra people, no clones.')
        prompts.append(prompt)
    return prompts

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
st.caption('Pour une image de référence, décris les personnes réellement présentes. Le programme ne les détecte pas automatiquement.')
people = st.selectbox('Nombre de personnes sur la photo', [2, 1, 3, 4], index=0)
action = st.selectbox('Mouvement précis de la scène 1',
    ['Libre', 'Femme assise se lève', 'Homme assis se lève', 'Les deux restent assis'])
locked = st.checkbox('Verrouiller les identités, interdire les doublons et conserver le décor', value=True)
if 'kc_prompts' not in st.session_state:
    st.session_state.kc_prompts = []
if st.button('Préparer mes scènes', type='primary', use_container_width=True):
    st.session_state.kc_prompts = scenes_from_text(idea.strip(), count, bool(photo_bytes), people, action, locked)
if st.session_state.kc_prompts:
    st.subheader('Scènes préparées')
    for i, p in enumerate(st.session_state.kc_prompts, 1):
        with st.expander(f'Scène {i}', expanded=i == 1):
            st.code(p, language=None)
            st.caption('Utilise ce prompt avec la même image de référence en mode image-vers-vidéo.')
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
                    video = generate(photo_bytes, 'karmaclip.png', scenes_from_text(idea, 1, True, people, action, locked)[0])
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

# ─────────────────────────────────────────────────────────────────────────────
# KarmaClip Agent V3: planning, approvals, resumable production and assembly.
# No claim of automated LoreMotion control: upload its resulting clips here.
# ─────────────────────────────────────────────────────────────────────────────
import hashlib
import subprocess
import tempfile
from pathlib import Path

st.divider()
st.header('🤖 KarmaClip Agent V3 · Projet musical')
st.caption('Storyboard → validation → séquences → montage. La génération LoreMotion reste manuelle tant que son pilotage n’est pas connecté.')

if 'agent_project' not in st.session_state:
    st.session_state.agent_project = None

with st.expander('📂 Reprendre un projet sauvegardé'):
    project_upload = st.file_uploader('Importer le projet JSON', type=['json'], key='agent_resume')
    if st.button('Charger le projet', key='agent_load') and project_upload:
        try:
            candidate = json.loads(project_upload.getvalue())
            if not isinstance(candidate, dict) or not isinstance(candidate.get('scenes'), list):
                raise ValueError('Format de projet non reconnu')
            st.session_state.agent_project = candidate
            st.success('Projet restauré. Les clips doivent être réimportés après un redémarrage du serveur.')
        except Exception as err:
            st.error(str(err))

agent_title = st.text_input('Titre du morceau', key='agent_title')
agent_audio = st.file_uploader('Chanson MP3, WAV ou M4A', type=['mp3','wav','m4a'], key='agent_audio')
agent_image = st.file_uploader('Pochette / image de référence (facultative)', type=['png','jpg','jpeg','webp'], key='agent_image')
agent_lyrics = st.text_area('Paroles ou résumé de l’histoire (facultatif)', height=130, key='agent_lyrics')
agent_style = st.text_area('Direction artistique', value='', placeholder='Décris librement le style de ton nouveau clip…', key='agent_style')
agent_people = st.number_input('Nombre exact de personnages récurrents', min_value=0, max_value=12, value=2, key='agent_people')
agent_seconds = st.slider('Durée cible par séquence (secondes)', 3, 10, 5, key='agent_seconds')
agent_duration = 0.0
if agent_audio:
    try:
        from mutagen import File as AudioFile
        audio_obj = AudioFile(io.BytesIO(agent_audio.getvalue()))
        if audio_obj and audio_obj.info:
            agent_duration = float(audio_obj.info.length)
    except Exception:
        pass
    if not agent_duration and agent_audio.name.lower().endswith('.wav'):
        try:
            import wave
            with wave.open(io.BytesIO(agent_audio.getvalue()), 'rb') as wav:
                agent_duration = wav.getnframes() / wav.getframerate()
        except Exception:
            pass
if agent_duration:
    st.caption(f'Durée musicale détectée : {agent_duration:.1f} secondes')
else:
    agent_duration = st.number_input('Durée du clip en secondes (si non détectée)', min_value=5, max_value=1200, value=120, step=5, key='agent_duration')

if st.button('🎬 Proposer mon storyboard', type='primary', use_container_width=True, key='agent_plan'):
    if not agent_title.strip():
        st.warning('Indique le titre du morceau.')
    else:
        import math
        n = min(240, max(1, math.ceil(agent_duration / agent_seconds)))
        sentences = [x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+', agent_lyrics) if x.strip()]
        phases = ['Présentation des personnages et du décor', 'Mise en mouvement et découverte', 'Évolution des relations et des enjeux', 'Moment fort et changement de rythme', 'Résolution visuelle et conclusion']
        scenes = []
        for idx in range(n):
            start = round(idx * agent_duration / n, 2)
            end = round((idx + 1) * agent_duration / n, 2)
            phase = phases[min(4, int(idx * 5 / n))]
            lyric = sentences[min(len(sentences)-1, idx * len(sentences) // n)] if sentences else ''
            movement = f'{phase}. {lyric}'.strip()
            scenes.append({'id':idx+1,'start':start,'end':end,'action':movement,'status':'à générer','engine':'LoreMotion','clip_name':''})
        st.session_state.agent_project = {'version':3,'title':agent_title,'style':agent_style,'characters':int(agent_people),'duration':agent_duration,'approved':False,'scenes':scenes}
        st.success(f'{n} scènes proposées. Modifie-les avant validation.')

project = st.session_state.agent_project
if project:
    st.subheader('Storyboard')
    st.caption('Le premier storyboard est une proposition structurée à partir du texte : aucune IA distante ni transcription audio n’est exécutée ici.')
    for i, scene in enumerate(project['scenes']):
        with st.expander(f"Scène {scene['id']:02d} · {scene['start']:.1f}–{scene['end']:.1f}s · {scene['status']}", expanded=(i==0)):
            scene['action'] = st.text_area('Action / intention', scene['action'], key=f"agent_action_{i}_{project['title']}")
            scene['engine'] = st.selectbox('Moteur souhaité', ['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'], index=(['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'].index(scene.get('engine','LoreMotion')) if scene.get('engine','LoreMotion') in ['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'] else 0), key=f"agent_engine_{i}_{project['title']}")
            people = project['characters']
            prompt = (f"Image-to-video, single uninterrupted shot, {scene['end']-scene['start']:.2f} seconds. "
                      f"Visual direction: {project['style']}. Scene action: {scene['action']}. "
                      f"The supplied reference image is the literal first frame. Exactly {people} recurring human characters; "
                      "preserve every existing character's unique face, clothing, position and anatomy. "
                      "Animate the ORIGINAL bodies through continuous physical movement, never create a new person to perform an action. "
                      "No clones, twins, extra people, morphing, teleportation, jump cuts, sudden appearance, or identity swaps. "
                      "When someone stands up, their original seated body rises and their original seat becomes empty. "
                      "Stable environment, consistent lighting, natural motion, coherent camera. Vertical 9:16, no text.")
            st.code(prompt, language=None)
            st.download_button('Télécharger le prompt', prompt, file_name=f"scene_{i+1:03d}_prompt.txt", key=f'agent_prompt_{i}')
            clip = st.file_uploader('Importer le clip généré (MP4)', type=['mp4'], key=f'agent_clip_{i}')
            if clip:
                scene['status'] = 'clip importé'
                scene['clip_name'] = clip.name
    if not project.get('approved'):
        if st.button('✅ Valider le storyboard', use_container_width=True, key='agent_approve'):
            project['approved'] = True
            st.success('Storyboard validé. Tu peux produire les scènes.')
    else:
        st.success('Storyboard validé')
    st.download_button('💾 Sauvegarder le projet JSON', json.dumps(project, ensure_ascii=False, indent=2), file_name='KarmaClip_projet.json', mime='application/json', use_container_width=True, key='agent_save')
    clip_files = [st.session_state.get(f'agent_clip_{i}') for i in range(len(project['scenes']))]
    available = sum(x is not None for x in clip_files)
    st.progress(available / max(1, len(clip_files)), text=f'{available}/{len(clip_files)} séquences importées')
    if available == len(clip_files) and project.get('approved') and agent_audio:
        if st.button('🎞️ Assembler le clip final', use_container_width=True, key='agent_assemble'):
            with st.spinner('Assemblage et synchronisation…'):
                try:
                    with tempfile.TemporaryDirectory() as folder:
                        root = Path(folder)
                        concat_lines = []
                        for i, video in enumerate(clip_files):
                            p = root / f'clip_{i:03d}.mp4'
                            p.write_bytes(video.getvalue())
                            concat_lines.append(f"file '{p.as_posix()}'")
                        listing = root / 'list.txt'
                        listing.write_text('\n'.join(concat_lines), encoding='utf-8')
                        suffix = Path(agent_audio.name).suffix.lower()
                        soundtrack = root / ('music' + (suffix if suffix in ('.mp3','.wav','.m4a') else '.mp3'))
                        soundtrack.write_bytes(agent_audio.getvalue())
                        output = root / 'final.mp4'
                        cmd = ['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),'-i',str(soundtrack),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-r','24','-c:a','aac','-shortest','-movflags','+faststart',str(output)]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
                        if result.returncode != 0 or not output.exists():
                            raise RuntimeError(result.stderr[-1200:] or 'FFmpeg indisponible')
                        st.session_state.agent_final_video = output.read_bytes()
                    st.success('Montage terminé')
                except Exception as err:
                    st.error('Montage impossible sur ce serveur : ' + str(err))
    elif available == len(clip_files) and not agent_audio:
        st.info('Ajoute la chanson pour assembler la vidéo et la bande-son.')
    if st.session_state.get('agent_final_video'):
        st.video(st.session_state.agent_final_video)
        st.download_button('⬇️ Télécharger le clip final', st.session_state.agent_final_video, file_name='KarmaClip_final.mp4', mime='video/mp4', use_container_width=True, key='agent_download')
