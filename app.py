"""KarmaClip Studio — interface simple, compatible avec requirements.txt existant.
LoreMotion: workflow manuel tant qu'aucune intégration serveur authentifiée n'est disponible.
Wan: tentative réelle via le module wan_nifty existant, disponibilité non garantie.
"""
import io
import re
import json
import zipfile
import hashlib
import subprocess
import tempfile
from pathlib import Path
import subprocess
import tempfile
from pathlib import Path
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


def kc_unified_prompt(action_en, camera_en='', continuity_en='', direction_en='', style_en='', people=2, duration=5, reference=True):
    """One shared, action-first prompt builder for both KarmaClip workflows.

    Never inserts a new action. The user action remains the primary instruction.
    """
    action_en = (action_en or '').strip()
    camera_en = (camera_en or '').strip()
    continuity_en = (continuity_en or '').strip()
    direction_en = (direction_en or '').strip()
    style_en = (style_en or '').strip()
    if not action_en:
        return ''
    motorcycle = bool(re.search(r'\b(motorcycl|motorbike|motorcycle|motard|moto|rider|ride|roul)\w*', action_en, re.I))
    sections = [
        f'IMAGE-TO-VIDEO, {duration:g} seconds, vertical 9:16.',
        f'PRIMARY ACTION (MANDATORY, DO NOT SUBSTITUTE): {action_en}',
    ]
    if motorcycle and re.search(r'\b(ride|riding|roul|driv|moving|forward)\w*', action_en, re.I):
        sections.append('RIDING PHYSICS: Riders stay seated on their own motorcycles throughout the shot, hands on handlebars, feet on footpegs. The motorcycles travel forward with rotating wheels; riders and motorcycles move together. No standing, dismounting, intersecting legs or overlapping motorcycles. Keep riders’ faces visible whenever possible without changing their original helmets or visors.')
    if camera_en:
        sections.append(f'CAMERA (FOLLOW USER INSTRUCTIONS): {camera_en}')
    if direction_en:
        sections.append(f'ADDITIONAL USER REQUIREMENTS: {direction_en}')
    if continuity_en:
        sections.append(f'CONTINUITY: {continuity_en}')
    if style_en:
        sections.append(f'VISUAL STYLE: {style_en}')
    if reference:
        sections.append('The supplied image is the literal first frame. Preserve the existing people, faces, outfits, vehicles, objects and environment. Do not invent new people or objects. If the requested starting pose is impossible from the reference, flag that a new starting image is needed instead of inventing a transition.')
    if people:
        sections.append(f'Keep the {people} original recurring characters consistent; never duplicate a person.')
    sections.append('One physically coherent continuous shot. No morphing, teleportation, limb intersections, sudden pose changes or unintended camera cuts. Do not add actions not requested by the user.')
    return '\n\n'.join(sections)


def scenes_from_text(text, count, identity, people=2, action='Libre', locked=True):
    """Same shared prompt builder used by the storyboard. Input should be English."""
    lines = [v.strip() for v in re.split(r'\n+|(?<=[.!?])\s+', text) if v.strip()]
    if not lines:
        return []
    specific = {
        'Femme assise se lève': 'The original seated woman stands up naturally from her own seat.',
        'Homme assis se lève': 'The original seated man stands up naturally from his own seat.',
        'Les deux restent assis': 'Both original people remain seated throughout the shot.',
    }
    prompts = []
    for i in range(count):
        instruction = lines[min(len(lines)-1, i * len(lines) // count)]
        if action != 'Libre' and i == 0 and action in specific:
            instruction += ' ' + specific[action]
        prompts.append(kc_unified_prompt(instruction, people=people, duration=5, reference=bool(identity and locked)))
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
engine = st.radio('Moteur', ['Wan 2.2 (direct, photo requise)', 'LoreMotion (externe : texte ou photo)', 'LTX (externe : texte ou photo)'], horizontal=False)
input_mode = st.radio('Entrée vidéo', ['Photo + texte', 'Texte seul'], horizontal=True)
if engine.startswith('Wan') and input_mode == 'Texte seul':
    st.warning('WAN direct nécessite une image de départ. Choisis Photo + texte, ou un moteur externe compatible texte-vers-vidéo.')
continuity_mode = st.selectbox('Image de départ des scènes suivantes', ['Dernière image de la vidéo précédente', 'Photo initiale', 'Image personnalisée par scène'], index=0)
custom_frames = {}
if continuity_mode == 'Image personnalisée par scène':
    st.caption('Pour une scène sans image spécifique, KarmaClip reprend la dernière image disponible.')
    for frame_index in range(2, min(301, int(st.session_state.get('kc_custom_count', 5)) + 1)):
        with st.expander(f'Image facultative — scène {frame_index}'):
            custom_upload = st.file_uploader('Remplacer la photo de départ', type=['png','jpg','jpeg','webp'], key=f'kc_custom_frame_{frame_index}')
            if custom_upload:
                custom_frames[frame_index] = normalize(custom_upload)
count = st.number_input('Nombre de scènes', min_value=1, max_value=300, value=5, step=1, key='kc_custom_count')
st.caption('WAN : génération séquentielle. Les démonstrations gratuites peuvent interrompre une série ; chaque clip réussi est conservé dans la session.')
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

if not engine.startswith('Wan'):
    st.info('Mode externe : prépare les prompts ici. La génération automatique et la récupération des vidéos ne sont pas connectées pour ce moteur. Texte seul possible si le modèle choisi sur le site le prend en charge.')
    if engine.startswith('LoreMotion'):
        st.link_button('🎥 Ouvrir LoreMotion', 'https://loremotion.com/', use_container_width=True)
    else:
        st.link_button('🎥 Ouvrir LTX Studio', 'https://ltx.studio/', use_container_width=True)
    if photo_bytes:
        st.download_button('⬇️ Photo prête pour LoreMotion', photo_bytes, 'KarmaClip_image.png', 'image/png', use_container_width=True)
else:
    st.caption('WAN 2.2 : génère les scènes dans l’ordre, en utilisant la dernière image de la vidéo précédente. Aucune garantie de quota sur le GPU public.')
    if 'kc_chain_clips' not in st.session_state:
        st.session_state.kc_chain_clips = []
    if 'kc_chain_frames' not in st.session_state:
        st.session_state.kc_chain_frames = []
    def kc_chain_last_frame(video_bytes):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'clip.mp4'
            output = Path(folder) / 'frame.png'
            source.write_bytes(video_bytes)
            probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                                    '-of','default=noprint_wrappers=1:nokey=1',str(source)],
                                   capture_output=True,text=True,timeout=20)
            if probe.returncode:
                raise RuntimeError('ffprobe : ' + probe.stderr[-300:])
            duration = float(probe.stdout.strip())
            position = max(0, duration - .12)
            result = subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                                     '-ss',str(position),'-i',str(source),'-frames:v','1',str(output)],
                                    capture_output=True,text=True,timeout=45)
            if result.returncode or not output.exists():
                raise RuntimeError('Extraction de la dernière image impossible : ' + result.stderr[-300:])
            return output.read_bytes()
    col_a, col_b = st.columns(2)
    with col_a:
        start_chain = st.button('🎬 Générer les scènes WAN',use_container_width=True)
    with col_b:
        reset_chain = st.button('🧹 Recommencer la série',use_container_width=True)
    if reset_chain:
        st.session_state.kc_chain_clips = []
        st.session_state.kc_chain_frames = []
        st.session_state.pop('kc_chain_config', None)
        st.session_state.pop('kc_chain_montage', None)
        st.rerun()
    if start_chain:
        if not photo_bytes or not idea.strip() or input_mode == 'Texte seul':
            st.warning('WAN direct exige une image de départ et une description. Choisis Photo + texte.')
        else:
            from wan_nifty import generate
            clips = st.session_state.kc_chain_clips
            frames = st.session_state.kc_chain_frames
            # Preserve results only while settings and reference image are unchanged.
            chain_config = (hashlib.sha256(photo_bytes).hexdigest(), idea, int(count), continuity_mode, people, action, locked, tuple(sorted((k,hashlib.sha256(v).hexdigest()) for k,v in custom_frames.items())))
            if clips and st.session_state.get('kc_chain_config') != chain_config:
                st.warning('Les réglages ont changé : recommence la série pour éviter de mélanger deux projets.')
                st.stop()
            st.session_state.kc_chain_config = chain_config
            if not clips:
                frames[:] = [photo_bytes]
            prompts = scenes_from_text(idea, int(count), True, people, action, locked)
            progress = st.progress(min(len(clips)/int(count),1.0))
            for index in range(len(clips), int(count)):
                try:
                    with st.spinner(f'WAN : scène {index+1}/{count}…'):
                        source_image = (photo_bytes if continuity_mode == 'Photo initiale' else custom_frames.get(index+1, frames[-1]))
                        video = generate(source_image,f'karmaclip_scene_{index+1}.png',prompts[index])
                        if not video or len(video) < 1024:
                            raise RuntimeError('Le moteur n’a pas retourné de vidéo valide')
                        # Extract before recording success so resume never skips a missing frame.
                        next_frame = kc_chain_last_frame(video)
                        clips.append(video)
                        frames.append(next_frame)
                    progress.progress((index+1)/int(count))
                except Exception as exc:
                    st.error(f'Scène {index+1} interrompue : {exc}. Les {len(clips)} clips réussis sont conservés ; relance pour reprendre.')
                    break
            if len(clips) >= int(count):
                st.success(f'{count} scènes générées. Tu peux les prévisualiser et les assembler.')
    clips = st.session_state.kc_chain_clips
    if clips:
        st.write(f'**{len(clips)}/{count} scènes disponibles**')
        for i, video in enumerate(clips):
            with st.expander(f'Scène WAN {i+1}',expanded=(i==len(clips)-1)):
                st.video(video)
                st.download_button('⬇️ Télécharger la scène',video,
                                   file_name=f'KarmaClip_WAN_{i+1:03d}.mp4',mime='video/mp4',key=f'kc_chain_dl_{i}')
        if st.button('🎞️ Assembler les scènes WAN',use_container_width=True):
            try:
                with tempfile.TemporaryDirectory() as folder:
                    root=Path(folder)
                    listing=[]
                    for i,clip in enumerate(clips):
                        target=root/f'clip_{i:03d}.mp4'
                        target.write_bytes(clip)
                        listing.append("file '"+str(target)+"'")
                    playlist=root/'concat.txt'
                    playlist.write_text('\n'.join(listing),encoding='utf-8')
                    output=root/'montage.mp4'
                    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0',
                         '-i',str(playlist),'-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',
                         '-movflags','+faststart',str(output)]
                    result=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
                    if result.returncode or not output.exists():
                        raise RuntimeError(result.stderr[-600:])
                    st.session_state.kc_chain_montage=output.read_bytes()
            except Exception as exc:
                st.error('Montage impossible : '+str(exc))
        if st.session_state.get('kc_chain_montage'):
            st.video(st.session_state.kc_chain_montage)
            st.download_button('⬇️ Télécharger le montage WAN',st.session_state.kc_chain_montage,
                               'KarmaClip_WAN_montage.mp4','video/mp4',use_container_width=True)

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

# V4: genuine audio feature extraction + optional multimodal LLM analysis.
import base64
import math
import os
import requests


def kc_audio_features(audio_bytes, filename):
    """Analyze the actual uploaded waveform, not only metadata or lyrics."""
    import numpy as np
    with tempfile.TemporaryDirectory() as d:
        source = Path(d) / ('input' + (Path(filename).suffix.lower() or '.mp3'))
        source.write_bytes(audio_bytes)
        cmd = ['ffmpeg', '-v', 'error', '-i', str(source), '-ac', '1', '-ar', '8000', '-f', 'f32le', '-']
        res = subprocess.run(cmd, capture_output=True, timeout=90)
        if res.returncode or not res.stdout:
            raise RuntimeError('Décodage audio impossible : FFmpeg indisponible ou format non reconnu.')
        a = np.frombuffer(res.stdout, dtype=np.float32)
        if len(a) < 8000:
            raise ValueError('Audio trop court pour une analyse.')
        sr = 8000
        hop = 2000  # energy every 250ms
        a = a[:(len(a)//hop)*hop]
        rms = np.sqrt(np.mean(a.reshape(-1, hop)**2, axis=1))
        smoothed = np.convolve(rms, np.ones(5)/5, mode='same')
        rise = np.maximum(0, np.diff(smoothed, prepend=smoothed[0]))
        peaks = np.where((rise[1:-1] > rise[:-2]) & (rise[1:-1] >= rise[2:]) & (rise[1:-1] > np.percentile(rise, 75)))[0] + 1
        duration = len(a) / sr
        # A rough onset estimate; not an authoritative musical BPM.
        onset_times = (peaks * hop / sr).tolist()
        tempo = None
        if len(onset_times) >= 5:
            diffs = np.diff(onset_times)
            diffs = diffs[(diffs >= .30) & (diffs <= 1.3)]
            if len(diffs) >= 3:
                tempo = round(60 / float(np.median(diffs)))
        nsections = max(1, math.ceil(duration/5))
        section_energy = []
        for i in range(nsections):
            chunk = rms[int(i*5*sr/hop):int((i+1)*5*sr/hop)]
            section_energy.append(round(float(np.mean(chunk)) if len(chunk) else 0, 5))
        return {'duration':round(duration,2),'estimated_bpm':tempo,'energy_5s':section_energy,'onsets':onset_times[:600], 'analysis':'waveform RMS / transient rises'}


def kc_openrouter_storyboard(api_key, model, photo_bytes, audio_features, lyrics, style, people, duration, seconds, direction=''):
    """Ask a vision-capable LLM to inspect actual image pixels and plan scenes."""
    if not photo_bytes:
        raise ValueError('Ajoute une image pour permettre une analyse visuelle réelle.')
    n = min(120, max(1, math.ceil(duration/seconds)))
    data_uri = 'data:image/png;base64,' + base64.b64encode(photo_bytes).decode('ascii')
    instructions = (
        'You are a precise film director, not a generic prompt writer. The USER INSTRUCTIONS below are binding, highest priority. Preserve every requested action, person, object, location, camera movement, sequence and chronology exactly; do not replace them with vague cinematic phrases. Separate long actions across adjacent shots without deleting any step. Add creative ideas only in portions not specified by the user, and never contradict explicit instructions. If an object is not visible in the starting image, introduce it in a coherent earlier shot or flag a required reference frame. Each scene action must describe WHO does WHAT, WHERE, WHEN and HOW, using concrete verbs and observable physical actions. Do not force a fixed camera when the user requests camera movement. USER INSTRUCTIONS: '+direction[:12000]+'\n Analyze the ACTUAL attached image, including visible characters, '
        'their initial poses, objects, background and camera framing. Use the ACTUAL audio measurements '
        'supplied below, and any supplied lyrics. Propose a cinematic realistic music-video storyboard '
        'with balanced creative freedom and strict continuity. Exactly one physically achievable main '
        'action per 5-second shot. No character cloning, no invented objects suddenly appearing. '
        'If a guitar must be used, it must already be visible or be introduced in a separate establishing shot. '
        'Each scene starts where the previous scene ended; for shots requiring a new composition, specify '
        'a separately generated reference frame. Do not claim to hear the song: audio measurements only. '
        'Return ONLY a JSON object with keys image_observations (string), music_interpretation (string), '
        'scenes (array of objects with action, camera, continuity, engine). '
        f'Create exactly {n} scenes, each approximately {seconds} seconds, for {duration:.1f} seconds total. '
        f'Expected recurring character count: {people}. Style: {style}. Lyrics: {lyrics[:12000]}. '
        f'Audio measurements: {json.dumps(audio_features, ensure_ascii=False)[:16000]}'
    )
    payload = {'model':model,'messages':[{'role':'user','content':[
        {'type':'text','text':instructions},
        {'type':'image_url','image_url':{'url':data_uri}}]}], 'temperature':0.65}
    response = requests.post('https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},
        json=payload,timeout=120)
    if not response.ok:
        raise RuntimeError(f'Analyse IA refusée ({response.status_code}): {response.text[:300]}')
    raw = response.json()['choices'][0]['message']['content']
    if isinstance(raw,list):
        raw=''.join(x.get('text','') for x in raw if isinstance(x,dict))
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.I)
    parsed = json.loads(raw)
    if not isinstance(parsed.get('scenes'),list) or len(parsed['scenes'])!=n:
        raise ValueError('L’IA n’a pas retourné le bon nombre de scènes. Réessaie.')
    return parsed

def kc_translate_scenes(api_key, model, scenes, direction, style):
    """Translate user-written French into English, without inventing actions."""
    if not api_key:
        raise ValueError('Ajoute une clé OpenRouter pour traduire automatiquement les scènes.')
    original = [{'id': scene['id'], 'action': scene.get('action',''),
                 'camera': scene.get('camera',''), 'continuity': scene.get('continuity','')}
                for scene in scenes]
    instruction = (
        'You are a professional film prompt translator, NOT a screenplay writer. '
        'Translate the supplied French into natural, technically precise English. '
        'Never invent, remove, reorder or replace any requested action, person, object, '
        'camera move or setting. Preserve ambiguity instead of guessing. '
        'Translate each field separately, keeping every id unchanged. '
        'Return ONLY valid JSON with a "scenes" array, each object having exactly '
        'id, action, camera, continuity; plus "direction" and "style" strings. '
        'Do not add cinematic clichés. Input: '+json.dumps({'scenes':original,
        'direction':direction,'style':style},ensure_ascii=False)
    )
    response=requests.post('https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},
        json={'model':model,'messages':[{'role':'user','content':instruction}],
              'temperature':0},timeout=120)
    if not response.ok:
        raise RuntimeError(f'Traduction indisponible ({response.status_code}): {response.text[:240]}')
    raw=response.json()['choices'][0]['message']['content']
    if isinstance(raw,list):
        raw=''.join(x.get('text','') for x in raw if isinstance(x,dict))
    raw=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(),flags=re.I)
    result=json.loads(raw)
    translated=result.get('scenes',[])
    if len(translated)!=len(original) or [x.get('id') for x in translated]!=[x['id'] for x in original]:
        raise ValueError('La traduction ne respecte pas les identifiants des scènes.')
    for item in translated:
        if not all(isinstance(item.get(k),str) and item[k].strip() for k in ('action','camera','continuity')):
            raise ValueError('Traduction incomplète : aucune scène n’a été modifiée.')
    return result



def kc_creative_proposal(api_key, model, scene, project, rejected):
    """Generate one genuinely new French shot proposal; no video generation."""
    if not api_key:
        raise ValueError('Ajoute une clé OpenRouter dans les réglages IA pour obtenir de nouvelles idées.')
    context = {
        'title':project.get('title',''), 'lyrics':project.get('lyrics','')[:3500],
        'style':project.get('style',''), 'user_direction':project.get('user_direction',''),
        'image_observations':project.get('image_observations',''),
        'music_interpretation':project.get('music_interpretation',''),
        'characters':project.get('characters',0),
        'scene_number':scene['id'], 'scene_start':scene['start'], 'scene_end':scene['end'],
        'previous_scene': next((x.get('action','') for x in project['scenes'] if x['id']==scene['id']-1),''),
        'next_scene': next((x.get('action','') for x in project['scenes'] if x['id']==scene['id']+1),''),
        'rejected_ideas':rejected[-12:]
    }
    instruction = ('You are an imaginative but physically realistic music-video director. '
        'Propose ONE original, surprising, filmable 5-second shot in FRENCH. '
        'The user explicitly requested creative invention for this scene, but preserve '
        'all explicit user constraints and the existing characters, motorcycles and setting. '
        'Exactly ONE clear physical action, coherent bodies and objects, no sudden teleportation, '
        'no unexplained standing up, no clones, no extra people. '
        'Differentiate substantially from rejected ideas. Do not merely paraphrase them. '
        'No generic mood-only suggestions. Return ONLY JSON with nonempty French strings '
        '"action", "camera", "continuity". Context: '+json.dumps(context,ensure_ascii=False))
    resp=requests.post('https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},
        json={'model':model,'messages':[{'role':'user','content':instruction}],
              'temperature':0.95},timeout=90)
    if not resp.ok:
        raise RuntimeError(f'Proposition IA indisponible ({resp.status_code}): {resp.text[:220]}')
    raw=resp.json()['choices'][0]['message']['content']
    if isinstance(raw,list):
        raw=''.join(x.get('text','') for x in raw if isinstance(x,dict))
    parsed=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(),flags=re.I))
    if not isinstance(parsed,dict) or not all(isinstance(parsed.get(k),str) and parsed[k].strip() for k in ('action','camera','continuity')):
        raise ValueError('La proposition IA est incomplète. Réessaie.')
    if parsed['action'].strip().casefold() in {v.strip().casefold() for v in rejected}:
        raise ValueError('Cette idée a déjà été proposée. Clique à nouveau sur Autre idée.')
    return {k:parsed[k].strip() for k in ('action','camera','continuity')}


st.divider()
st.header('🎬 KarmaClip Agent · Réalisateur IA')
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
agent_direction = st.text_area('🎯 Mes instructions exactes — à respecter impérativement', placeholder='Décris précisément ce qui doit arriver, dans quel ordre, et ce qui est interdit. Ces instructions sont prioritaires sur les propositions de l’IA.', key='agent_direction', height=160)
agent_style = st.text_area('Direction artistique', value='', placeholder='Cinématographique réaliste, liberté créative équilibrée, continuité activée', key='agent_style')
st.caption('Style par défaut : cinéma réaliste · créativité équilibrée · continuité stricte')
with st.expander('🧠 Analyse IA réelle de l’image (connexion facultative)'):
    kc_key = st.text_input('Clé API OpenRouter', type='password', key='kc_or_key', help='Clé utilisée uniquement pour cette requête ; ne la colle pas dans GitHub.')
    kc_model = st.text_input('Modèle avec vision compatible OpenRouter', value='qwen/qwen2.5-vl-72b-instruct:free', key='kc_or_model')
    st.caption('Un modèle gratuit peut être indisponible ou limité. La clé et un modèle vision fonctionnel sont indispensables pour analyser réellement l’image.')
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

if st.button('🎬 Analyser la chanson et proposer mon storyboard', type='primary', use_container_width=True, key='agent_plan'):
    if not agent_title.strip() or not agent_audio:
        st.warning('Ajoute un titre et une chanson pour analyser le morceau.')
    else:
        try:
            with st.spinner('Analyse des variations d’intensité et des attaques musicales…'):
                features = kc_audio_features(agent_audio.getvalue(), agent_audio.name)
            st.session_state.kc_audio_analysis = features
            duration = features['duration']
            n = min(120, max(1, math.ceil(duration / agent_seconds)))
            ai = None
            if kc_key and agent_image:
                with st.spinner('Analyse visuelle de l’image et création du storyboard par IA…'):
                    ai = kc_openrouter_storyboard(kc_key, kc_model, normalize(agent_image), features,
                        agent_lyrics, agent_style or 'cinematic realistic, balanced creativity, strict continuity',
                        int(agent_people), duration, agent_seconds, agent_direction)
            scenes = []
            phases = ['Présentation du décor et des personnages','Premier mouvement discret','Développement de l’action','Moment émotionnel fort','Résolution et plan final']
            for idx in range(n):
                start_t = round(idx*agent_seconds,2)
                end_t = round(min(duration,(idx+1)*agent_seconds),2)
                if ai:
                    item = ai['scenes'][idx]
                    action = str(item.get('action','Plan contemplatif, mouvement subtil'))
                    camera = str(item.get('camera','Caméra stable'))
                    continuity = str(item.get('continuity','Conserver identités et décor'))
                    engine = str(item.get('engine','LoreMotion'))
                else:
                    energy = features['energy_5s'][min(idx,len(features['energy_5s'])-1)]
                    baseline = max(features['energy_5s']) or 1
                    intensity = 'calme' if energy/baseline < .35 else ('modérée' if energy/baseline < .7 else 'énergique')
                    action = phases[min(4,int(idx*5/n))] + f'. Mouvement {intensity}, une seule action continue.'
                    camera = 'Caméra fixe ou déplacement très lent'
                    continuity = 'Conserver les personnes et objets visibles sans apparition'
                    engine = 'LoreMotion'
                scenes.append({'id':idx+1,'start':start_t,'end':end_t,'action':action,
                               'camera':camera,'continuity':continuity,'status':'à générer',
                               'engine':engine if engine in ['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'] else 'LoreMotion',
                               'clip_name':''})
            st.session_state.agent_project = {'version':4,'title':agent_title,'style':agent_style or 'Cinématographique réaliste, créativité équilibrée',
                'characters':int(agent_people),'user_direction':agent_direction,'duration':duration,'approved':False,'scenes':scenes,
                'audio_analysis':features,'image_observations':ai.get('image_observations','') if ai else '',
                'music_interpretation':ai.get('music_interpretation','') if ai else '',
                'ai_analyzed':bool(ai)}
            if ai:
                st.success(f'{n} scènes créées avec analyse visuelle IA et analyse audio réelle.')
            else:
                st.warning(f'{n} scènes préparées avec analyse réelle de l’énergie audio, mais sans analyse IA de l’image. Fournis une clé et un modèle vision pour le storyboard personnalisé.')
        except Exception as err:
            st.error('Analyse impossible : '+str(err))

project = st.session_state.agent_project
if project:
    st.subheader('Storyboard')
    if project.get('user_direction'):
        st.info('Consignes prioritaires conservées mot pour mot : '+project['user_direction'])
    st.caption('Analyse du signal audio effectuée. Analyse visuelle IA : '+('oui' if project.get('ai_analyzed') else 'non — storyboard de secours générique')+'. La transcription des paroles n’est pas automatique.')
    if project.get('image_observations'):
        st.info('Image observée : '+project['image_observations'])
    if project.get('music_interpretation'):
        st.info('Interprétation musicale : '+project['music_interpretation'])
    if project.get('audio_analysis'):
        st.caption('Tempo estimé (approximatif) : '+str(project['audio_analysis'].get('estimated_bpm') or 'non déterminé')+' BPM')
    st.markdown('#### Traduction française → anglaise')
    st.caption('Après avoir modifié les scènes en français, clique sur Traduire. La traduction utilise le modèle OpenRouter configuré plus haut. Sans clé, aucun faux résultat anglais n’est affiché.')
    if st.button('🌍 Traduire toutes les scènes en anglais', key='agent_translate', use_container_width=True):
        try:
            with st.spinner('Traduction fidèle des actions, caméras et consignes…'):
                translated=kc_translate_scenes(kc_key,kc_model,project['scenes'],
                    project.get('user_direction',''),project.get('style',''))
            for scene, english in zip(project['scenes'],translated['scenes']):
                scene['english']=english
                scene['translated_from']={k:scene.get(k,'') for k in ('action','camera','continuity')}
            project['direction_en']=translated.get('direction','')
            project['style_en']=translated.get('style','')
            st.success('Traduction prête. Vérifie les prompts ci-dessous.')
        except Exception as err:
            st.error('Traduction impossible : '+str(err))
    if project.get('approved'):
        st.caption('Toute modification des scènes après validation nécessite une nouvelle validation.')
    st.caption('Mode fidèle : tu écris les actions. Mode Inspiration IA : tu peux demander autant de propositions que nécessaire (selon les quotas du modèle), sans lancer de vidéo.')
    for i, scene in enumerate(project['scenes']):
        with st.expander(f"Scène {scene['id']:02d} · {scene['start']:.1f}–{scene['end']:.1f}s · {scene['status']}", expanded=(i==0)):
            mode_key=f'kc_creative_mode_{i}_{project["title"]}'
            mode=st.radio('Méthode de création', ['Mes instructions (fidèle)', 'Inspiration IA (propositions)'],
                          horizontal=True, key=mode_key)
            proposal_key=f'kc_creative_proposal_{i}_{project["title"]}'
            rejected_key=f'kc_creative_rejected_{i}_{project["title"]}'
            if mode.startswith('Inspiration'):
                st.caption('Une proposition française à la fois. Rien ne remplace ta scène sans ton accord.')
                if st.button('✨ Proposer une idée' if not st.session_state.get(proposal_key) else '🔄 Autre idée',
                             key=f'kc_creative_next_{i}_{project["title"]}'):
                    if st.session_state.get(proposal_key):
                        st.session_state.setdefault(rejected_key,[]).append(st.session_state[proposal_key]['action'])
                    try:
                        with st.spinner('Le réalisateur imagine une autre scène…'):
                            st.session_state[proposal_key]=kc_creative_proposal(
                                kc_key,kc_model,scene,project,st.session_state.get(rejected_key,[]))
                    except Exception as err:
                        st.error(str(err))
                proposed=st.session_state.get(proposal_key)
                if proposed:
                    st.markdown('**Proposition en français**')
                    st.write('Action : '+proposed['action'])
                    st.write('Caméra : '+proposed['camera'])
                    st.write('Continuité : '+proposed['continuity'])
                    if st.button('✅ J’aime cette idée — intégrer à la scène', key=f'kc_creative_accept_{i}_{project["title"]}'):
                        for field in ('action','camera','continuity'):
                            scene[field]=proposed[field]
                            st.session_state[f'agent_{field}_{i}_{project["title"]}']=proposed[field]
                        scene.pop('english',None)
                        scene.pop('translated_from',None)
                        project['approved']=False
                        st.session_state.pop(proposal_key,None)
                        st.success('Idée intégrée. Tu peux la modifier, puis traduire en anglais et valider.')
                        st.rerun()
            scene['action'] = st.text_area('Action / intention', scene['action'], key=f"agent_action_{i}_{project['title']}")
            scene['camera'] = st.text_input('Caméra', scene.get('camera','Caméra stable'), key=f"agent_camera_{i}_{project['title']}")
            scene['continuity'] = st.text_input('Continuité', scene.get('continuity','Identités et décor constants'), key=f"agent_continuity_{i}_{project['title']}")
            scene['engine'] = st.selectbox('Moteur souhaité', ['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'], index=(['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'].index(scene.get('engine','LoreMotion')) if scene.get('engine','LoreMotion') in ['LoreMotion','Wan 2.2','LTX (si disponible)','Autre'] else 0), key=f"agent_engine_{i}_{project['title']}")
            people = project['characters']
            english = scene.get('english',{})
            current={k:scene.get(k,'') for k in ('action','camera','continuity')}
            translated_ok = bool(english) and current==scene.get('translated_from')
            if translated_ok:
                action_en=english['action']
                camera_en=english['camera']
                continuity_en=english['continuity']
                direction_en=project.get('direction_en','')
                style_en=project.get('style_en','')
            else:
                action_en=camera_en=continuity_en=direction_en=style_en=None
            if not translated_ok:
                st.warning('Cette scène n’a pas de traduction anglaise à jour. Traduis les scènes avant de copier le prompt.')
            prompt = kc_unified_prompt(
                action_en or '[TRANSLATION REQUIRED]',
                camera_en or '', continuity_en or '', direction_en or '', style_en or '',
                people=people, duration=scene['end']-scene['start'], reference=True)
            st.code(prompt, language=None)
            st.download_button('Télécharger le prompt anglais', prompt, file_name=f"scene_{i+1:03d}_prompt.txt", key=f'agent_prompt_{i}', disabled=not translated_ok)
            clip = st.file_uploader('Importer le clip généré (MP4)', type=['mp4'], key=f'agent_clip_{i}')
            if clip:
                scene['status'] = 'clip importé'
                scene['clip_name'] = clip.name
    # Continuité automatique : extraction de la dernière image du clip précédent.
    # Le fichier reste local à la session Streamlit, sans appel à un service externe.
    def kc_last_frame(video_bytes):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'scene.mp4'
            target = Path(folder) / 'last_frame.png'
            source.write_bytes(video_bytes)
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(source)],
                capture_output=True, text=True, timeout=20)
            if probe.returncode:
                raise RuntimeError(probe.stderr.strip() or 'Vidéo illisible')
            duration = float(probe.stdout.strip())
            if duration <= 0:
                raise ValueError('Durée de la vidéo invalide')
            # Position juste avant la fin pour éviter les frames noires de clôture.
            position = max(0.0, duration - min(0.12, duration / 2))
            extraction = subprocess.run(
                ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                 '-ss', f'{position:.3f}', '-i', str(source),
                 '-frames:v', '1', str(target)],
                capture_output=True, text=True, timeout=45)
            if extraction.returncode or not target.exists():
                raise RuntimeError(extraction.stderr.strip() or 'Extraction impossible')
            return target.read_bytes()

    st.markdown('#### 🔗 Continuité automatique entre les scènes')
    st.caption('Après import de la scène N, récupère son image finale comme référence de la scène N+1. '
               'Les personnages et le décor restent à contrôler : une image extraite ne garantit pas leur fidélité.')
    for idx in range(len(project['scenes']) - 1):
        previous_clip = st.session_state.get(f'agent_clip_{idx}')
        if previous_clip is None:
            continue
        clip_data = previous_clip.getvalue()
        fingerprint = hashlib.sha256(clip_data).hexdigest()
        frame_key = f'kc_frame_{idx}'
        if st.session_state.get(frame_key + '_hash') != fingerprint:
            try:
                st.session_state[frame_key] = kc_last_frame(clip_data)
                st.session_state[frame_key + '_hash'] = fingerprint
                st.session_state.pop(frame_key + '_error', None)
            except Exception as exc:
                st.session_state.pop(frame_key, None)
                st.session_state[frame_key + '_hash'] = fingerprint
                st.session_state[frame_key + '_error'] = str(exc)
        with st.expander(f'Image de liaison · scène {idx+1} → scène {idx+2}', expanded=(idx == 0)):
            if st.session_state.get(frame_key + '_error'):
                st.error('Extraction impossible : ' + st.session_state[frame_key + '_error'])
            elif st.session_state.get(frame_key):
                st.image(st.session_state[frame_key], caption=f'Dernière image de la scène {idx+1}', width=280)
                st.download_button(
                    f'⬇️ Image de départ pour la scène {idx+2}',
                    st.session_state[frame_key],
                    file_name=f'KarmaClip_scene_{idx+2:03d}_reference.png',
                    mime='image/png', key=f'kc_download_frame_{idx}', use_container_width=True)
                st.info(f'Pour générer la scène {idx+2}, importe cette image dans LoreMotion en mode image-vers-vidéo, '
                        f'puis utilise le prompt anglais de la scène {idx+2}. '
                        'Ne réutilise pas la première photo si tu souhaites poursuivre le mouvement.')
    if not project.get('approved'):
        if st.button('✅ Valider le storyboard', use_container_width=True, key='agent_approve'):
            project['approved'] = True
            st.success('Storyboard validé. Tu peux produire les scènes.')
    else:
        st.success('Storyboard validé')
    st.download_button('💾 Sauvegarder le projet JSON', json.dumps(project, ensure_ascii=False, indent=2), file_name='KarmaClip_projet.json', mime='application/json', use_container_width=True, key='agent_save')
    # Dossier de production : un prompt par plan, une feuille de suivi, la référence.
    # Ne simule aucune génération distante : ce paquet facilite la production manuelle
    # ou une future intégration officielle/API.
    import csv
    from datetime import datetime
    def kc_production_bundle(current, source_image):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            sheet = io.StringIO()
            writer = csv.writer(sheet)
            writer.writerow(['scene', 'debut_s', 'fin_s', 'moteur', 'instruction_fr', 'prompt_en', 'statut'])
            for idx, item in enumerate(current['scenes'], 1):
                french = str(item.get('action', ''))
                parts = item.get('english') or {}
                fresh = bool(parts) and item.get('translated_from') == {k:item.get(k,'') for k in ('action','camera','continuity')}
                english = ('ACTION: ' + str(parts.get('action','')) + '\nCAMERA: ' + str(parts.get('camera','')) + '\nCONTINUITY: ' + str(parts.get('continuity','')) + '\nSTYLE: ' + str(current.get('style_en','')) + '\nDIRECTION: ' + str(current.get('direction_en',''))) if fresh else ''
                writer.writerow([idx, item.get('start', ''), item.get('end', ''), item.get('engine', 'LoreMotion'), french, english, item.get('status', '')])
                z.writestr(f'scenes/scene_{idx:03d}_FR.txt', french)
                z.writestr(f'scenes/scene_{idx:03d}_EN.txt', english if english else 'TRADUCTION ANGLAISE NON DISPONIBLE : traduire cette scène avant production.')
            z.writestr('suivi_scenes.csv', sheet.getvalue().encode('utf-8-sig'))
            z.writestr('projet.json', json.dumps(current, ensure_ascii=False, indent=2))
            z.writestr('LISEZ_MOI.txt', 'KarmaClip Agent - dossier de production\n1. Vérifier les prompts EN, puis générer chaque scène dans LoreMotion.\n2. Utiliser la même image de référence ou la dernière frame selon le plan.\n3. Télécharger chaque MP4 et le réimporter dans KarmaClip.\n4. Valider les clips avant assemblage.\nAucune automatisation LoreMotion n’est incluse.\n')
            if source_image:
                try:
                    z.writestr('reference.png', normalize(source_image))
                except Exception:
                    pass
        return output.getvalue()
    st.download_button('📦 Télécharger le dossier complet de production (ZIP)',
        kc_production_bundle(project, agent_image),
        file_name='KarmaClip_production.zip', mime='application/zip',
        use_container_width=True, key='agent_bundle')

    # Contrôle technique des clips importés, sans juger à tort leur qualité artistique.
    def kc_probe_clip(raw):
        with tempfile.NamedTemporaryFile(suffix='.mp4') as temp:
            temp.write(raw)
            temp.flush()
            check = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,duration', '-show_entries', 'format=duration',
                '-of', 'json', temp.name], capture_output=True, text=True, timeout=20)
            if check.returncode:
                raise RuntimeError(check.stderr.strip() or 'ffprobe indisponible')
            data = json.loads(check.stdout)
            stream = (data.get('streams') or [{}])[0]
            duration = float(stream.get('duration') or data.get('format', {}).get('duration') or 0)
            return duration, int(stream.get('width') or 0), int(stream.get('height') or 0)

    with st.expander('🔎 Vérification technique des vidéos importées'):
        for i, item in enumerate(project['scenes']):
            uploaded = st.session_state.get(f'agent_clip_{i}')
            if uploaded:
                try:
                    dur, width, height = kc_probe_clip(uploaded.getvalue())
                    expected = float(item['end']) - float(item['start'])
                    issues = []
                    if abs(dur - expected) > 1.0:
                        issues.append(f'durée {dur:.1f}s au lieu de {expected:.1f}s')
                    if width and height and width >= height:
                        issues.append(f'format {width}×{height} non vertical')
                    if issues:
                        st.warning(f"Scène {i+1} : " + ' ; '.join(issues))
                    else:
                        st.success(f'Scène {i+1} : {dur:.1f}s, {width}×{height} — format conforme')
                except Exception as exc:
                    st.warning(f'Scène {i+1} : vérification impossible ({exc})')
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
