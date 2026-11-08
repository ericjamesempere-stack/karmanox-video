import io, json, zipfile, shutil, subprocess, tempfile, re
from pathlib import Path
import streamlit as st
from PIL import Image, ImageOps, ImageEnhance

st.set_page_config(page_title='KarmaClip Studio',page_icon='🎬',layout='centered',initial_sidebar_state='collapsed')
STEPS=['🎨 Image','✍️ Storyboard','🎥 LoreMotion','🎞️ Montage']
ENGINES={'LoreMotion':'https://loremotion.com/generate/','WAN':'https://wan2.video/fr/free-ai-video-generator','NiftyVid':'https://igorcsis.github.io/nifty-vid/'}
DEFAULT={'step':STEPS[0],'project':'Mon clip','idea':'','lyrics':'','style':'Cinématographique','format':'9:16','image':None,'image_prompt':'','video_prompt':'','movement':'Mouvement naturel et fluide','camera':'Travelling lent','mood':'Cinématographique','duration':5,'continuity':True,'scenes':[],'engine':'LoreMotion','final':None,'music':None,'clip_data':{},'clip_order':[],'title':'','artist':''}
for k,v in DEFAULT.items():
    if 'kc_'+k not in st.session_state: st.session_state['kc_'+k]=v
s=st.session_state
st.markdown('''<style>.block-container{max-width:850px;padding-top:1rem;padding-bottom:4rem}div.stButton button,div.stDownloadButton button,div.stLinkButton a{min-height:48px;border-radius:12px}div[data-testid="stImage"] img{border-radius:14px}h1,h2{letter-spacing:-.025em}</style>''',unsafe_allow_html=True)

def go(x): s.kc_step=x

def nav(label,x,primary=True): st.button(label,on_click=go,args=(x,),type='primary' if primary else 'secondary',use_container_width=True)

def png(im):
    b=io.BytesIO();im.convert('RGB').save(b,'PNG');return b.getvalue()

def video_prompt(scene=None):
    subject=scene if scene is not None else s.kc_idea
    return '\n'.join([f'Scene: {subject or "Animate the reference image"}.',f'Movement: {s.kc_movement}.',f'Camera: {s.kc_camera}.',f'Mood: {s.kc_mood}.',f'Duration: {s.kc_duration} seconds.','Preserve identity, face, clothes, and environment across shots.' if s.kc_continuity else 'Allow visual changes between shots.','Smooth coherent motion, cinematic framing, no watermark.'])

def make_scenes(text,n):
    lines=[x.strip() for x in text.splitlines() if x.strip() and not x.strip().startswith('[')] or [s.kc_idea or 'A surprising cinematic scene']
    out=[]
    for i in range(n):
        desc=' '.join(lines[i*len(lines)//n:(i+1)*len(lines)//n]).strip() or lines[i%len(lines)]
        out.append({'id':i+1,'description':desc,'locked':False})
    return out

def project_zip():
    data={k:s.get('kc_'+k) for k in DEFAULT if k not in ('image','final','music','clip_data')}
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',json.dumps(data,ensure_ascii=False,indent=2))
        if s.kc_image:z.writestr('image.png',s.kc_image)
    return b.getvalue()

def restore_callback():
    try:
        f=s.get('restore_upload')
        if f is None:return
        with zipfile.ZipFile(io.BytesIO(f.getvalue())) as z:
            data=json.loads(z.read('project.json'))
            for k,v in DEFAULT.items():
                if k in data and k not in ('image','final','music','clip_data') and isinstance(data[k],type(v)):s['kc_'+k]=data[k]
            if 'image.png' in z.namelist():
                with Image.open(io.BytesIO(z.read('image.png'))) as im:s.kc_image=png(ImageOps.exif_transpose(im))
        s.restore_status='Projet restauré.'
    except Exception as e:s.restore_status=f'Restauration impossible : {e}'

def reset():
    for k in list(s):
        if k.startswith('kc_'):del s[k]

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode:raise RuntimeError('Vidéo illisible : '+p.stderr[-250:])
    return float(p.stdout.strip())

def ff(args,timeout=240):
    p=subprocess.run(['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error',*map(str,args)],capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stderr[-700:] or 'Erreur FFmpeg')

def effect_filters(item):
    """Filtres FFmpeg réels, sans service payant."""
    effect=item.get('effect','Aucun')
    strength=max(0.0,min(1.0,float(item.get('intensity',0.5))))
    filters=[]
    if effect=='Noir et blanc': filters.append('hue=s=0')
    elif effect=='Vintage': filters.append(f'eq=saturation={1-.5*strength:.3f}:contrast={1+.08*strength:.3f}:gamma_r={1+.12*strength:.3f}:gamma_b={1-.1*strength:.3f}')
    elif effect=='Cinéma': filters.append(f'eq=contrast={1+.22*strength:.3f}:saturation={1-.12*strength:.3f}')
    elif effect=='Couleurs vives': filters.append(f'eq=saturation={1+1.3*strength:.3f}:contrast={1+.12*strength:.3f}')
    elif effect=='Lumineux': filters.append(f'eq=brightness={.16*strength:.3f}:gamma={1+.1*strength:.3f}')
    elif effect=='Sombre': filters.append(f'eq=brightness={-.22*strength:.3f}:contrast={1+.15*strength:.3f}')
    elif effect=='Froid': filters.append(f'colorbalance=rs={-.22*strength:.3f}:bs={.28*strength:.3f}')
    elif effect=='Chaud': filters.append(f'colorbalance=rs={.25*strength:.3f}:bs={-.2*strength:.3f}')
    elif effect=='Flou': filters.append(f'boxblur=luma_radius={int(1+8*strength)}:luma_power=1')
    elif effect=='Netteté': filters.append(f'unsharp=5:5:{.2+1.3*strength:.2f}:5:5:0')
    elif effect=='Vignette': filters.append(f'vignette=angle={.2+.5*strength:.3f}')
    elif effect=='Grain': filters.append(f'noise=alls={int(4+30*strength)}:allf=t')
    elif effect=='Miroir': filters.append('hflip')
    elif effect=='Flash': filters.append(f'eq=brightness={.08+.18*strength:.3f}')
    if item.get('mirror') and effect!='Miroir':filters.append('hflip')
    return filters

def render_montage(items,music,fmt):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise RuntimeError('FFmpeg/FFprobe indisponible sur le serveur.')
    sizes={'9:16':(720,1280),'1:1':(1080,1080),'16:9':(1280,720)}
    w,h=sizes[fmt]
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);segments=[]
        for i,item in enumerate(items):
            src=root/f'src_{i}.mp4';src.write_bytes(item['bytes'])
            duration=probe(src)
            start=min(float(item['start']),max(0,duration-.1));end=min(float(item['end']),duration)
            if end-start<.15:raise ValueError(f'Scène {i+1} : découpe trop courte.')
            speed=float(item['speed']);dst=root/f'seg_{i}.mp4'
            vf=f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,setpts=PTS/{speed}'
            filters=effect_filters(item)
            vf+=(','+','.join(filters)) if filters else ''
            seglen=(end-start)/speed
            fade=min(float(item.get('fade',0.0)),max(0,seglen/2-.02))
            if fade>0:
                vf+=f',fade=t=in:st=0:d={fade:.3f},fade=t=out:st={max(0,seglen-fade):.3f}:d={fade:.3f}'
            vf+=',format=yuv420p' 
            ff(['-ss',start,'-i',src,'-t',end-start,'-vf',vf,'-an','-c:v','libx264','-preset','ultrafast','-crf','26',dst])
            segments.append(dst)
        manifest=root/'list.txt';manifest.write_text(''.join(f"file '{p.name}'\n" for p in segments))
        joined=root/'joined.mp4';ff(['-f','concat','-safe','0','-i',manifest,'-c','copy',joined])
        if music:
            suffix=Path(music['name']).suffix.lower();suffix=suffix if suffix in ('.mp3','.wav','.m4a') else '.mp3'
            audio=root/('music'+suffix);audio.write_bytes(music['bytes']);final=root/'final.mp4'
            ff(['-i',joined,'-i',audio,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',final])
            return final.read_bytes()
        return joined.read_bytes()

st.title('🎬 KarmaClip Studio')
st.caption('Une idée → des scènes → LoreMotion → ton clip')
with st.expander('📁 Mon projet / sauvegarde'):
    st.text_input('Nom du projet',key='kc_project')
    st.download_button('💾 Sauvegarder le storyboard',project_zip(),file_name='KarmaClip_projet.zip',mime='application/zip',use_container_width=True)
    st.file_uploader('Restaurer un projet ZIP',type=['zip'],key='restore_upload')
    st.button('Restaurer',on_click=restore_callback,use_container_width=True)
    st.button('🧹 Nouveau projet',on_click=reset,use_container_width=True)
    st.caption('Le ZIP contient les textes et l’image, pas les vidéos volumineuses. Sauvegarde-le sur ton téléphone.')
if s.get('restore_status'):st.info(s.pop('restore_status'))
st.radio('Navigation',STEPS,key='kc_step',horizontal=True,label_visibility='collapsed')
st.divider()

if s.kc_step==STEPS[0]:
    st.header('🎨 Ton idée et ton image')
    st.text_area('Décris ce que tu veux créer',key='kc_idea',height=110,placeholder='Un personnage danse dans un monde qui change autour de lui…')
    a,b=st.columns(2)
    with a:st.selectbox('Style',['Cinématographique','Photoréaliste','Anime / manga','Fantastique','Surréaliste','Vintage','Illustration','Noir et blanc'],key='kc_style')
    with b:st.selectbox('Format',['9:16','1:1','16:9'],key='kc_format')
    with st.expander('🎵 Paroles / scénario'):
        st.text_area('Paroles ou histoire',key='kc_lyrics',height=170)
        st.text_input('Titre du single',key='kc_title');st.text_input('Artiste',key='kc_artist')
    s.kc_image_prompt=f'Create an original {s.kc_style} visual, aspect ratio {s.kc_format}. Subject: {s.kc_idea}. Inspired by: {s.kc_lyrics[:450]}. Detailed, expressive, coherent, professional composition, no watermark.'
    with st.expander('✨ Prompt image préparé'):
        st.code(s.kc_image_prompt,language=None)
        st.caption('Tu peux copier le prompt pour ton générateur d’images. Une génération IA intégrée nécessiterait un service connecté.')
    st.markdown('### 📸 Importer et retoucher')
    up=st.file_uploader('Photo ou image créée',type=['jpg','jpeg','png','webp'],key='image_upload')
    if up:
        try:
            with Image.open(io.BytesIO(up.getvalue())) as im:result=ImageOps.exif_transpose(im).convert('RGB')
            with st.expander('🎛️ Retouches'):
                brightness=st.slider('Luminosité',.2,2.,1.,.1);contrast=st.slider('Contraste',.2,2.,1.,.1);color=st.slider('Couleur',0.,2.,1.,.1)
            result=ImageEnhance.Brightness(result).enhance(brightness)
            result=ImageEnhance.Contrast(result).enhance(contrast)
            result=ImageEnhance.Color(result).enhance(color)
            w,h={'9:16':(1080,1920),'1:1':(3000,3000),'16:9':(1920,1080)}[s.kc_format]
            result=ImageOps.fit(result,(w,h),method=Image.Resampling.LANCZOS)
            st.image(result,use_container_width=True)
            raw=png(result)
            st.download_button('⬇️ Télécharger cette image',raw,'KarmaClip_image.png','image/png',use_container_width=True)
            if st.button('✅ Garder cette image dans mon projet',type='primary',use_container_width=True):s.kc_image=raw;st.success('Image enregistrée dans ce projet.')
        except Exception as e:st.error(str(e))
    if s.kc_image:st.image(s.kc_image,caption='Image de référence conservée',width=230)
    nav('✍️ Préparer le storyboard',STEPS[1])

elif s.kc_step==STEPS[1]:
    st.header('✍️ Mon storyboard')
    st.caption('Tu peux modifier, déplacer, verrouiller ou supprimer chaque scène.')
    if s.kc_image:st.image(s.kc_image,width=220)
    with st.expander('🎬 Direction artistique',expanded=True):
        st.text_area('Idée principale',key='kc_idea',height=85)
        st.text_input('Mouvements',key='kc_movement')
        st.selectbox('Caméra',['Travelling lent','Caméra fixe','Travelling avant','Travelling arrière','Rotation autour du sujet','Caméra à l’épaule'],key='kc_camera')
        st.selectbox('Ambiance',['Cinématographique','Festive','Dynamique','Mystérieuse','Épique','Romantique','Naturelle'],key='kc_mood')
        st.selectbox('Durée par génération',[3,4,5,6,8,10],key='kc_duration')
        st.checkbox('Conserver les personnages et le décor',key='kc_continuity')
    st.markdown('### 🎞️ Découper en scènes')
    count=st.number_input('Nombre de scènes',1,60,6)
    if st.button('✨ Construire le storyboard',use_container_width=True):
        old=[x for x in s.kc_scenes if x.get('locked')]
        fresh=make_scenes(s.kc_lyrics or s.kc_idea,int(count))
        for i,x in enumerate(old):
            if i<len(fresh):fresh[i]=x
        s.kc_scenes=fresh;st.rerun()
    if not s.kc_scenes:st.info('Crée le storyboard, ou ajoute directement une scène.')
    def move_scene(i,offset):
        j=i+offset
        if 0<=j<len(s.kc_scenes):s.kc_scenes[i],s.kc_scenes[j]=s.kc_scenes[j],s.kc_scenes[i]
    def remove_scene(i):s.kc_scenes.pop(i)
    for i,scene in enumerate(s.kc_scenes):
        with st.container(border=True):
            st.markdown(f'**Scène {i+1} · 5 secondes** '+('🔒' if scene.get('locked') else ''))
            # Separate widget keys ensure edits persist until explicitly changed.
            edit_key=f'edit_scene_{scene["id"]}'
            if edit_key not in s:s[edit_key]=scene['description']
            scene['description']=st.text_area('Action et décor',key=edit_key,height=85)
            scene['locked']=st.checkbox('Verrouiller cette scène',value=scene.get('locked',False),key=f'lock_{scene["id"]}')
            with st.expander('Prompt vidéo de cette scène'):st.code(video_prompt(scene['description']),language=None)
            a,b,c=st.columns(3)
            with a:st.button('⬆️ Monter',key=f'up_{scene["id"]}',on_click=move_scene,args=(i,-1),disabled=i==0,use_container_width=True)
            with b:st.button('⬇️ Descendre',key=f'down_{scene["id"]}',on_click=move_scene,args=(i,1),disabled=i==len(s.kc_scenes)-1,use_container_width=True)
            with c:st.button('🗑️ Supprimer',key=f'del_{scene["id"]}',on_click=remove_scene,args=(i,),use_container_width=True)
    if st.button('➕ Ajouter une scène',use_container_width=True):
        new_id=max([x['id'] for x in s.kc_scenes],default=0)+1
        s.kc_scenes.append({'id':new_id,'description':'Nouvelle idée à développer','locked':False});st.rerun()
    st.caption('Pour inventer des scènes vraiment nouvelles avec une IA, il faudra connecter un modèle : les descriptions actuelles proviennent de ton texte et restent entièrement modifiables.')
    s.kc_video_prompt=video_prompt()
    nav('🎥 Continuer vers LoreMotion',STEPS[2])

elif s.kc_step==STEPS[2]:
    st.header('🎥 Générer mes vidéos')
    st.caption('LoreMotion est sélectionné par défaut. Les autres moteurs restent disponibles.')
    if s.kc_image:
        st.image(s.kc_image,width=250)
        st.download_button('⬇️ Télécharger l’image de référence',s.kc_image,'KarmaClip_reference.png','image/png',use_container_width=True)
    st.selectbox('Générateur',list(ENGINES),key='kc_engine')
    st.link_button('🚀 Ouvrir la page de création — '+s.kc_engine,ENGINES[s.kc_engine],use_container_width=True)
    st.caption('Le site externe s’ouvre directement sur sa page de génération. Il ne reçoit pas automatiquement les champs du projet.')
    if not s.kc_video_prompt:s.kc_video_prompt=video_prompt()
    st.text_area('Prompt principal',key='kc_video_prompt',height=180)
    if s.kc_scenes:
        st.markdown('### 🎞️ Prompts par scène')
        for i,scene in enumerate(s.kc_scenes):
            with st.expander(f'Scène {i+1} — prêt à copier'):
                st.code(video_prompt(scene['description']),language=None)
    nav('🎞️ Mes MP4 sont prêts : montage',STEPS[3])

else:
    st.header('🎞️ Mon montage')
    st.caption('Importe tes vidéos de LoreMotion, règle les scènes et exporte un MP4.')
    uploaded=st.file_uploader('Importer les séquences MP4',type=['mp4'],accept_multiple_files=True,key='montage_upload')
    if uploaded:
        for f in uploaded:
            # Fingerprint distinguishes same-named uploads.
            raw=f.getvalue();ident=f'{f.name}:{len(raw)}:{hash(raw[:4096])}'
            if ident not in s.kc_clip_data:
                s.kc_clip_data[ident]={'name':f.name,'bytes':raw,'start':0.,'end':5.,'speed':1.,'effect':'Aucun','intensity':0.5,'transition':'Aucune','fade':0.0,'mirror':False,'volume':1.0}
                s.kc_clip_order.append(ident)
    if s.kc_clip_order:
        st.markdown('### 🎬 Mes scènes dans l’ordre')
        def move_clip(i,offset):
            j=i+offset
            if 0<=j<len(s.kc_clip_order):s.kc_clip_order[i],s.kc_clip_order[j]=s.kc_clip_order[j],s.kc_clip_order[i]
        def remove_clip(i):
            key=s.kc_clip_order.pop(i);s.kc_clip_data.pop(key,None)
        for i,key in enumerate(s.kc_clip_order):
            item=s.kc_clip_data[key]
            with st.expander(f'🎬 {i+1}. {item["name"]}',expanded=i==0):
                st.video(item['bytes'])
                st.caption('Découpe : secondes à conserver dans cette vidéo.')
                a,b=st.columns(2)
                with a:item['start']=st.number_input('Début (s)',min_value=0.,value=float(item['start']),step=.5,key=f'start_{key}')
                with b:item['end']=st.number_input('Fin (s)',min_value=.2,value=float(item['end']),step=.5,key=f'end_{key}')
                item['speed']=st.select_slider('Vitesse',options=[.5,.75,1.,1.25,1.5,2.],value=float(item['speed']),key=f'speed_{key}')
                with st.expander('✨ Effets et transitions',expanded=i==0):
                    effects=['Aucun','Cinéma','Vintage','Noir et blanc','Couleurs vives','Lumineux','Sombre','Froid','Chaud','Flou','Netteté','Vignette','Grain','Miroir','Flash']
                    item['effect']=st.selectbox('Effet visuel',effects,index=effects.index(item.get('effect','Aucun')) if item.get('effect','Aucun') in effects else 0,key=f'effect_{key}')
                    item['intensity']=st.slider('Intensité',0.0,1.0,float(item.get('intensity',0.5)),0.1,key=f'intensity_{key}')
                    item['fade']=st.select_slider('Fondu au noir (entrée et sortie)',options=[0.,.2,.4,.6,1.],value=float(item.get('fade',0.0)),key=f'fade_{key}')
                    item['mirror']=st.checkbox('Inverser horizontalement',value=bool(item.get('mirror',False)),key=f'mirror_{key}')
                    st.caption('Les effets seront appliqués lors de l’export. Le fondu se fait au noir entre les séquences.')
                a,b,c=st.columns(3)
                with a:st.button('⬆️',key=f'clipup_{key}',on_click=move_clip,args=(i,-1),disabled=i==0,use_container_width=True)
                with b:st.button('⬇️',key=f'clipdown_{key}',on_click=move_clip,args=(i,1),disabled=i==len(s.kc_clip_order)-1,use_container_width=True)
                with c:st.button('🗑️',key=f'clipdel_{key}',on_click=remove_clip,args=(i,),use_container_width=True)
    music=st.file_uploader('🎵 Bande-son (MP3, WAV ou M4A)',type=['mp3','wav','m4a'],key='montage_music')
    if music:st.audio(music)
    fmt=st.selectbox('Format de sortie',['9:16','1:1','16:9'],index=0)
    ready=bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    if not ready:st.warning('FFmpeg et FFprobe doivent être installés sur Render pour assembler les vidéos.')
    if st.button('🎬 Exporter mon clip',type='primary',use_container_width=True,disabled=not s.kc_clip_order or not ready):
        try:
            items=[s.kc_clip_data[k] for k in s.kc_clip_order]
            soundtrack={'name':music.name,'bytes':music.getvalue()} if music else None
            with st.spinner('Montage en cours…'):s.kc_final=render_montage(items,soundtrack,fmt)
            st.success('Ton clip est prêt !')
        except Exception as e:st.error(f'Export impossible : {e}')
    if s.kc_final:
        st.video(s.kc_final)
        st.download_button('⬇️ Télécharger mon clip final',s.kc_final,'KarmaClip_final.mp4','video/mp4',use_container_width=True)
    st.link_button('✂️ Ouvrir CapCut (montage avancé)','https://www.capcut.com/editor',use_container_width=True)
    st.caption('Montage intégré : ordre, découpe, vitesse, 14 effets visuels, intensité, miroir, fondu au noir et musique. Les effets ne s’affichent qu’après export. Les transitions animées, sous-titres automatiques et suivi IA ne sont pas encore disponibles.')

st.divider();st.caption('KarmaClip Studio · Image → Storyboard → LoreMotion → Montage')
