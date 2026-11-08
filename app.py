import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageOps

st.set_page_config(page_title='KarmaClip Studio', page_icon='🎬', layout='centered')
st.markdown('''<style>.block-container{max-width:850px;padding-top:1rem}div.stButton button,div.stDownloadButton button,div.stLinkButton a{min-height:46px;border-radius:12px}</style>''',unsafe_allow_html=True)

if 'project' not in st.session_state:
    st.session_state.project={'name':'Mon clip','idea':'','lyrics':'','style':'Cinématographique','ratio':'9:16','duration':5,'count':6,'scenes':[],'image':None,'music':None,'music_name':'','clips':[],'final':None}
p=st.session_state.project

ENGINES={'LoreMotion':'https://loremotion.com/','WAN 2.2':'https://wan2.video/','LTX Video':'https://ltx.studio/','Vidu':'https://www.vidu.com/'}

def generate_scenes(idea,lyrics,count,duration,style):
    key=os.environ.get('GEMINI_API_KEY','').strip()
    if not key:
        try:key=st.secrets.get('GEMINI_API_KEY','')
        except Exception:key=''
    if not key:raise RuntimeError('Clé Gemini absente. Utilise le mode ChatGPT ou manuel.')
    model=os.environ.get('GEMINI_MODEL','gemini-2.5-flash')
    prompt=f'''Tu réalises un clip musical original. Réponds uniquement avec un JSON valide ayant la forme {{"scenes":[{{"description":"...","prompt":"...","transition":"..."}}]}}. EXACTEMENT {count} scènes de {duration} secondes. Chaque prompt est en anglais, précis, avec action, caméra, décor, lumière et continuité. Style: {style}. Idée: {idea}. Paroles: {lyrics[:12000]}. Pas de clichés ni répétitions.'''
    response=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key},json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':8192}},timeout=60)
    if response.status_code!=200:raise RuntimeError(f'Gemini HTTP {response.status_code}: {response.text[:250]}')
    raw=''.join(part.get('text','') for part in response.json()['candidates'][0]['content']['parts'])
    return parse_scenes(raw)

def parse_scenes(raw):
    raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip())
    data=json.loads(raw)
    if isinstance(data,dict) and 'proposals' in data:data=data['proposals'][0]
    items=data.get('scenes',[]) if isinstance(data,dict) else data
    if not isinstance(items,list) or not 1<=len(items)<=60:raise ValueError('Le JSON doit contenir 1 à 60 scènes.')
    scenes=[]
    for i,item in enumerate(items):
        if not isinstance(item,dict) or not str(item.get('prompt','')).strip():raise ValueError(f'Prompt manquant scène {i+1}')
        scenes.append({'description':str(item.get('description','')),'prompt':str(item['prompt']),'transition':str(item.get('transition','')),'locked':False})
    return scenes

def chatgpt_prompt():
    return f'''Crée un scénario de clip musical original, cohérent, avec exactement {p['count']} scènes de {p['duration']} secondes. Style : {p['style']}. Idée : {p['idea']}. Paroles : {p['lyrics']}. Réponds uniquement avec du JSON valide, sans Markdown, sous la forme {{"scenes":[{{"description":"description en français","prompt":"detailed English video prompt with action and camera movement","transition":"raccord"}}]}}. Préserve la continuité des personnages et décors.'''

def ffmpeg(args,timeout=300):
    proc=subprocess.run(['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error',*map(str,args)],capture_output=True,text=True,timeout=timeout)
    if proc.returncode:raise RuntimeError(proc.stderr[-600:] or 'Erreur FFmpeg')

def video_duration(path):
    proc=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,timeout=20)
    if proc.returncode:raise RuntimeError('MP4 illisible')
    return float(proc.stdout.strip())

def make_montage(quality,volume):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise RuntimeError('FFmpeg absent sur le serveur. Installer ffmpeg dans le déploiement.')
    if not p['clips']:raise RuntimeError('Importe au moins une vidéo.')
    sizes={'480p':(480,854),'720p':(720,1280),'1080p':(1080,1920)}
    w,h=sizes[quality]
    if p['ratio']=='16:9':w,h=h,w
    if p['ratio']=='1:1':w=h=min(w,h)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);segments=[]
        for i,clip in enumerate(p['clips']):
            path=Path(clip['path'])
            if not path.exists():raise RuntimeError('Vidéo temporaire perdue : réimporte les MP4.')
            dur=video_duration(path);start=max(0.0,float(clip['start']));end=min(dur,float(clip['end']));speed=float(clip['speed'])
            if end-start<0.2:raise RuntimeError(f'Découpe incorrecte pour vidéo {i+1}')
            vf=f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,setpts=(PTS-STARTPTS)/{speed}'
            effect=clip['effect']
            if effect=='Noir et blanc':vf+=',hue=s=0'
            elif effect=='Cinéma':vf+=',eq=contrast=1.15:saturation=0.9'
            elif effect=='Vintage':vf+=',eq=saturation=0.65'
            elif effect=='Couleurs vives':vf+=',eq=saturation=1.5'
            elif effect=='Miroir':vf+=',hflip'
            vf+=',format=yuv420p'
            target=root/f'part{i:03}.mp4'
            ffmpeg(['-ss',start,'-i',path,'-t',end-start,'-vf',vf,'-an','-c:v','libx264','-threads','1','-preset','ultrafast','-crf','29',target],timeout=300)
            segments.append(target)
        manifest=root/'list.txt';manifest.write_text(''.join(f"file '{x.name}'\n" for x in segments))
        joined=root/'joined.mp4';ffmpeg(['-f','concat','-safe','0','-i',manifest,'-c','copy',joined])
        final=root/'final.mp4'
        if p['music']:
            suffix=Path(p['music_name']).suffix or '.mp3';music=root/('music'+suffix);music.write_bytes(p['music'])
            ffmpeg(['-i',joined,'-i',music,'-map','0:v:0','-map','1:a:0','-filter:a',f'volume={volume}','-c:v','copy','-c:a','aac','-shortest','-movflags','+faststart',final])
        else:shutil.copyfile(joined,final)
        return final.read_bytes()

st.title('🎬 KarmaClip Studio')
st.caption('Une idée → un scénario → des vidéos → un clip MP4')
with st.expander('📁 Sauvegarder ou restaurer mon projet'):
    metadata={k:v for k,v in p.items() if k not in ('image','music','clips','final')}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',json.dumps(metadata,ensure_ascii=False,indent=2))
        if p['image']:z.writestr('reference.png',p['image'])
        if p['music']:z.writestr('music'+(Path(p['music_name']).suffix or '.mp3'),p['music'])
    st.download_button('💾 Sauvegarder mon projet ZIP',output.getvalue(),'KarmaClip_projet.zip','application/zip',use_container_width=True)
    backup=st.file_uploader('Restaurer un projet ZIP',type=['zip'],key='restore')
    if backup and st.button('Restaurer'):
        try:
            with zipfile.ZipFile(io.BytesIO(backup.getvalue())) as z:
                data=json.loads(z.read('project.json'))
                for key in metadata:
                    if key in data:p[key]=data[key]
                p['image']=z.read('reference.png') if 'reference.png' in z.namelist() else None
                tracks=[name for name in z.namelist() if name.startswith('music.')]
                if tracks:p['music_name']=tracks[0];p['music']=z.read(tracks[0])
                p['clips']=[];p['final']=None
            st.success('Projet restauré');st.rerun()
        except Exception as exc:st.error(str(exc))
    st.caption('Les MP4 ne sont pas inclus dans cette sauvegarde.')

step=st.radio('Étape',['1 · Image','2 · Scénario','3 · Génération vidéo','4 · Montage'],horizontal=True)
st.divider()

if step.startswith('1'):
    st.subheader('1 · Image de référence')
    p['name']=st.text_input('Nom du projet',value=p['name'])
    p['idea']=st.text_area('Ton idée, même en trois mots',value=p['idea'],height=110)
    p['style']=st.selectbox('Style visuel',['Cinématographique','Photoréaliste','Anime / manga','Surréaliste','Vintage','Fantastique'],index=['Cinématographique','Photoréaliste','Anime / manga','Surréaliste','Vintage','Fantastique'].index(p['style']) if p['style'] in ['Cinématographique','Photoréaliste','Anime / manga','Surréaliste','Vintage','Fantastique'] else 0)
    p['ratio']=st.selectbox('Format',['9:16','1:1','16:9'],index=['9:16','1:1','16:9'].index(p['ratio']))
    st.write('**Prompt image à copier dans ChatGPT :**')
    st.code(f"Crée une image {p['ratio']} pour un clip musical, style {p['style']}. Sujet : {p['idea']}. Visuel original, composition cinématographique, sans texte ni logo.",language=None)
    st.link_button('Créer mon image dans ChatGPT','https://chatgpt.com/',use_container_width=True)
    uploaded=st.file_uploader('Importer ma photo / image (facultatif)',type=['png','jpg','jpeg','webp'],key='image_upload')
    if uploaded:
        try:
            im=ImageOps.exif_transpose(Image.open(io.BytesIO(uploaded.getvalue()))).convert('RGB');im.thumbnail((1400,1400));buffer=io.BytesIO();im.save(buffer,format='PNG');p['image']=buffer.getvalue()
        except Exception as exc:st.error(str(exc))
    if p['image']:
        st.image(p['image'],caption='Image du projet',use_container_width=True)
        st.download_button('⬇️ Enregistrer mon image',p['image'],'reference.png','image/png')
    st.info('L’image est facultative : tu peux continuer uniquement avec ton idée.')

elif step.startswith('2'):
    st.subheader('2 · Mon scénario')
    p['idea']=st.text_area('Idée du clip',value=p['idea'],height=90)
    p['lyrics']=st.text_area('Paroles (facultatif)',value=p['lyrics'],height=160)
    audio=st.file_uploader('Musique MP3, WAV ou M4A (facultatif)',type=['mp3','wav','m4a'],key='song')
    if audio:p['music']=audio.getvalue();p['music_name']=audio.name
    if p['music']:st.audio(p['music'])
    a,b=st.columns(2)
    with a:p['count']=st.number_input('Nombre de scènes',min_value=1,max_value=60,value=int(p['count']))
    with b:p['duration']=st.selectbox('Secondes par scène',[3,4,5,6,8,10],index=[3,4,5,6,8,10].index(p['duration']) if p['duration'] in [3,4,5,6,8,10] else 2)
    if st.button('✨ Générer le scénario avec Gemini',type='primary',use_container_width=True):
        try:
            with st.spinner('Génération des scènes...'):p['scenes']=generate_scenes(p['idea'],p['lyrics'],p['count'],p['duration'],p['style'])
            st.success('Scénario créé !')
        except Exception as exc:st.error(str(exc))
    st.write('**Alternative ChatGPT :**')
    st.code(chatgpt_prompt(),language=None)
    st.link_button('Ouvrir ChatGPT','https://chatgpt.com/',use_container_width=True)
    raw=st.text_area('Colle ici le JSON renvoyé par ChatGPT',height=130,key='scenario_json')
    if st.button('Importer le scénario ChatGPT'):
        try:p['scenes']=parse_scenes(raw);st.success('Scénario importé !')
        except Exception as exc:st.error(str(exc))
    st.markdown('### Mes scènes')
    for i,scene in enumerate(p['scenes']):
        with st.expander(f'Scène {i+1}',expanded=i==0):
            scene['description']=st.text_area('Description',value=scene['description'],key=f'd_{i}')
            scene['prompt']=st.text_area('Prompt vidéo',value=scene['prompt'],key=f'p_{i}',height=110)
            scene['locked']=st.checkbox('Verrouiller',value=scene.get('locked',False),key=f'l_{i}')
            up,down,delete=st.columns(3)
            with up:up_click=st.button('⬆️ Monter',key=f'up_{i}',disabled=i==0,use_container_width=True)
            with down:down_click=st.button('⬇️ Descendre',key=f'down_{i}',disabled=i==len(p['scenes'])-1,use_container_width=True)
            with delete:delete_click=st.button('🗑️',key=f'delete_{i}',use_container_width=True)
            if up_click:p['scenes'][i-1],p['scenes'][i]=p['scenes'][i],p['scenes'][i-1];st.rerun()
            if down_click:p['scenes'][i+1],p['scenes'][i]=p['scenes'][i],p['scenes'][i+1];st.rerun()
            if delete_click:p['scenes'].pop(i);st.rerun()
    if st.button('➕ Ajouter une scène'):
        p['scenes'].append({'description':'','prompt':'','transition':'','locked':False});st.rerun()

elif step.startswith('3'):
    st.subheader('3 · Générer les vidéos')
    engine=st.selectbox('Moteur vidéo',list(ENGINES))
    st.link_button(f'🚀 Ouvrir {engine}',ENGINES[engine],use_container_width=True)
    st.info('Copie le prompt de chaque scène dans le générateur choisi, puis télécharge les MP4. Les sites externes ne sont pas pilotés automatiquement par cette application.')
    if p['image']:
        st.image(p['image'],width=220)
        st.download_button('Télécharger l’image de référence',p['image'],'reference.png','image/png')
    if not p['scenes']:st.warning('Crée ou importe des scènes à l’étape 2.')
    for i,scene in enumerate(p['scenes']):
        with st.expander(f'Scène {i+1} · {p["duration"]} s',expanded=i==0):
            st.write(scene.get('description',''));st.code(scene.get('prompt',''),language=None)
    st.caption('Si un moteur est indisponible, sélectionne un autre moteur dans la liste.')

else:
    st.subheader('4 · Montage et export MP4')
    st.caption('Les fichiers vidéo restent temporaires sur le serveur : télécharge le MP4 final dès sa création.')
    uploads=st.file_uploader('Importer les MP4 dans l’ordre souhaité',type=['mp4'],accept_multiple_files=True,key='videos')
    if uploads:
        known={clip['id'] for clip in p['clips']}
        for upload in uploads:
            import hashlib
            raw=upload.getvalue();identifier=hashlib.sha256(raw).hexdigest()
            if identifier in known:continue
            target=Path(tempfile.gettempdir())/f'karmaclip_{identifier}.mp4';target.write_bytes(raw)
            try:duration=video_duration(target)
            except Exception:duration=5.0
            p['clips'].append({'id':identifier,'name':upload.name,'path':str(target),'start':0.0,'end':duration,'speed':1.0,'effect':'Aucun'});known.add(identifier)
    for i,clip in enumerate(p['clips']):
        with st.expander(f'{i+1} · {clip["name"]}',expanded=i==0):
            if Path(clip['path']).exists():st.video(clip['path'])
            a,b=st.columns(2)
            with a:clip['start']=st.number_input('Début (s)',min_value=0.0,value=float(clip['start']),step=0.1,key=f'start_{clip["id"]}')
            with b:clip['end']=st.number_input('Fin (s)',min_value=0.2,value=float(clip['end']),step=0.1,key=f'end_{clip["id"]}')
            clip['speed']=st.select_slider('Vitesse',options=[0.5,0.75,1.0,1.25,1.5,2.0],value=float(clip['speed']),key=f'speed_{clip["id"]}')
            effects=['Aucun','Cinéma','Vintage','Noir et blanc','Couleurs vives','Miroir']
            clip['effect']=st.selectbox('Effet',effects,index=effects.index(clip['effect']),key=f'effect_{clip["id"]}')
            a,b,c=st.columns(3)
            with a:up=st.button('⬆️',key=f'vu_{clip["id"]}',disabled=i==0)
            with b:down=st.button('⬇️',key=f'vd_{clip["id"]}',disabled=i==len(p['clips'])-1)
            with c:delete=st.button('🗑️',key=f'vx_{clip["id"]}')
            if up:p['clips'][i-1],p['clips'][i]=p['clips'][i],p['clips'][i-1];st.rerun()
            if down:p['clips'][i+1],p['clips'][i]=p['clips'][i],p['clips'][i+1];st.rerun()
            if delete:p['clips'].pop(i);st.rerun()
    music=st.file_uploader('Musique de fond (facultatif)',type=['mp3','wav','m4a'],key='music_montage')
    if music:p['music']=music.getvalue();p['music_name']=music.name
    if p['music']:st.audio(p['music'])
    volume=st.slider('Volume musique',0.0,2.0,1.0,0.1)
    quality=st.selectbox('Qualité',['480p','720p','1080p'])
    if not shutil.which('ffmpeg'):st.warning('FFmpeg doit être installé sur le serveur Render.')
    if st.button('🎬 Générer le film MP4',type='primary',use_container_width=True,disabled=not bool(p['clips'])):
        try:
            with st.spinner('Montage en cours...'):p['final']=make_montage(quality,volume)
            st.success('Ton clip est prêt !')
        except Exception as exc:st.error(str(exc))
    if p['final']:
        st.video(p['final']);st.download_button('⬇️ Télécharger mon film MP4',p['final'],'KarmaClip_final.mp4','video/mp4',use_container_width=True)
    st.link_button('📱 Ouvrir CapCut sur Android','https://play.google.com/store/apps/details?id=com.lemon.lvoverseas',use_container_width=True)

st.divider()
st.caption('KarmaClip Studio · Android · Gemini / ChatGPT · LoreMotion · FFmpeg')
