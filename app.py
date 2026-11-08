import io, os, re, json, zipfile, shutil, subprocess, tempfile, hashlib, math
from pathlib import Path
import requests
import streamlit as st
from PIL import Image, ImageOps, ImageEnhance

st.set_page_config(page_title='KarmaClip Studio', page_icon='🎬', layout='centered', initial_sidebar_state='collapsed')
st.markdown("""
<style>
/* KarmaClip — interface mobile, sans bibliothèques supplémentaires */
.block-container{max-width:850px;padding-top:1.15rem;padding-bottom:3rem}
h1{font-weight:850!important;letter-spacing:-.035em;line-height:1.12!important}
h2,h3{letter-spacing:-.02em}
p{line-height:1.55}
div.stButton button,div.stDownloadButton button,div.stLinkButton a{
 min-height:48px;border-radius:14px!important;font-weight:650;
 transition:filter .16s ease,transform .16s ease
}
div.stButton button:hover,div.stDownloadButton button:hover,div.stLinkButton a:hover{
 filter:brightness(1.08);transform:translateY(-1px)
}
div.stButton button[kind="primary"]{
 background:linear-gradient(110deg,#e33b70,#ef704a)!important;
 color:white!important;border:0!important;box-shadow:0 5px 18px #e33b7030
}
div[data-testid="stFileUploader"]{
 border-radius:16px;overflow:hidden
}
div[data-testid="stFileUploaderDropzone"]{border-radius:14px}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:17px}
div[data-testid="stAlert"]{border-radius:14px}
div[data-testid="stRadio"] label{font-weight:600}
div[data-testid="stRadio"] [role="radiogroup"]{
 display:flex;flex-wrap:wrap;gap:.45rem
}
div[data-testid="stRadio"] [role="radiogroup"]>label{
 border:1px solid #8884;padding:.35rem .65rem;border-radius:12px;
 margin:0;background:rgba(140,140,140,.07)
}
div[data-testid="stTextArea"] textarea,div[data-testid="stTextInput"] input{
 border-radius:12px
}
.kc-hero{
 background:linear-gradient(125deg,rgba(229,53,112,.16),rgba(246,154,64,.09) 56%,rgba(100,120,230,.1));
 border:1px solid rgba(220,120,145,.28);border-radius:19px;
 padding:1rem 1.15rem;margin:.2rem 0 1.05rem
}
.kc-hero-title{font-size:1.15rem;font-weight:800;letter-spacing:-.02em}
.kc-hero-sub{opacity:.83;font-size:.91rem;margin-top:.3rem;line-height:1.5}
.kc-progress{font-size:.85rem;opacity:.82;margin:.35rem 0 .8rem}
@media(max-width:600px){
 .block-container{padding-left:1rem;padding-right:1rem}
 h1{font-size:2rem!important}
 div.stButton button,div.stDownloadButton button,div.stLinkButton a{min-height:52px}
}
</style>
""",unsafe_allow_html=True)
ENGINES={'LoreMotion':'https://loremotion.com/generate/','WAN 2.2':'https://wan2.video/fr/free-ai-video-generator','NiftyVid':'https://igorcsis.github.io/nifty-vid/'}
STEPS=['1 · Image','2 · Scénario IA','3 · Vidéo','4 · Montage']
DEFAULT={'step':0,'name':'Mon clip','idea':'','lyrics':'','style':'Cinématographique','format':'9:16','image':None,'music':None,'music_name':'','audio_report':None,'scenes':[],'proposals':[],'chosen':0,'continuity':True,'scene_seconds':5,'scene_count':6,'engine':'LoreMotion','clips':{},'order':[],'final':None,'project_seed':0,'export_quality':'480p','export_crf':29}
for k,v in DEFAULT.items():
    if 'kc_'+k not in st.session_state: st.session_state['kc_'+k]=v
s=st.session_state

def gemini_key():
    return os.environ.get('GEMINI_API_KEY','').strip() or st.secrets.get('GEMINI_API_KEY','')

def gemini(prompt, max_tokens=8192):
    key=gemini_key()
    if not key: raise RuntimeError('Clé GEMINI_API_KEY absente sur le serveur Render.')
    # REST endpoint; no extra Google SDK required. Model can be overridden on Render.
    model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    payload={'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{'temperature':0.95,'maxOutputTokens':max_tokens,'responseMimeType':'application/json'}}
    # Deux tentatives courtes évitent l'attente de 110 secondes sur Android.
    for attempt in range(2):
        try:
            r=requests.post(url,headers={'x-goog-api-key':key,'Content-Type':'application/json'},json=payload,timeout=(10,45))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == 0:
                continue
            raise RuntimeError('⏳ Gemini met trop de temps à répondre. Ton idée et tes réglages sont conservés : appuie à nouveau sur « Créer 3 scénarios » dans quelques instants.')
        except requests.RequestException:
            raise RuntimeError('Connexion à Gemini momentanément indisponible. Réessaie dans quelques instants.')
        if r.status_code in (500,502,503,504) and attempt == 0:
            continue
        break
    if r.status_code!=200:
        try: msg=r.json().get('error',{}).get('message',r.text[:400])
        except Exception: msg=r.text[:400]
        if r.status_code==429: raise RuntimeError('Quota Gemini gratuit atteint. Réessaie plus tard ; aucune facturation n’est déclenchée par KarmaClip.')
        if r.status_code in (500,502,503,504): raise RuntimeError('Gemini est temporairement surchargé. Réessaie dans quelques instants : tes données sont conservées.')
        raise RuntimeError(f'Gemini ({r.status_code}) : {msg}')
    try:
        data=r.json();parts=data['candidates'][0]['content']['parts'];raw=''.join(p.get('text','') for p in parts)
        raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip())
        return json.loads(raw)
    except Exception as e: raise RuntimeError(f'Réponse Gemini inexploitable : {e}. Réessaie.')

def audio_analysis(raw, name):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        return {'note':'FFmpeg indisponible : analyse audio non réalisable sur ce serveur.','duration':None,'energy':[]}
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/('audio'+Path(name).suffix.lower());p.write_bytes(raw)
        meta=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(p)],capture_output=True,text=True,timeout=30)
        if meta.returncode: raise RuntimeError('Format audio illisible.')
        duration=float(meta.stdout.strip())
        # Downsample to 4 kHz mono for lightweight energy analysis.
        q=subprocess.run(['ffmpeg','-v','error','-i',str(p),'-ac','1','-ar','4000','-f','s16le','-'],capture_output=True,timeout=100)
        if q.returncode: raise RuntimeError('Décodage audio impossible.')
        import array
        pcm=array.array('h');pcm.frombytes(q.stdout[:120000000])
        bucket=4000*5;energy=[]
        for i in range(0,len(pcm),bucket):
            chunk=pcm[i:i+bucket]
            if not chunk:continue
            rms=math.sqrt(sum(float(x)*x for x in chunk)/len(chunk))/32768
            energy.append(round(rms,4))
        changes=sorted(range(1,len(energy)),key=lambda i:abs(energy[i]-energy[i-1]),reverse=True)[:12]
        return {'duration':round(duration,1),'energy':energy,'changes_seconds':sorted(i*5 for i in changes),'note':'Énergie mesurée toutes les 5 secondes. Les paroles sont interprétées à partir du texte fourni ; le BPM et le genre ne sont pas déduits automatiquement.'}

def creative_brief():
    a=s.kc_audio_report or {}
    return {'idea':s.kc_idea,'style':s.kc_style,'lyrics':s.kc_lyrics[:15000], 'music_analysis':a,'number_of_scenes':int(s.kc_scene_count),'seconds_per_scene':int(s.kc_scene_seconds),'continuity':s.kc_continuity,'image_reference':bool(s.kc_image),'random_direction_seed':s.kc_project_seed}

def new_proposals():
    brief=creative_brief()
    prompt='''Tu es un réalisateur de clips musicaux exceptionnellement inventif. Réponds UNIQUEMENT avec un objet JSON valide de la forme {"proposals":[{"title":"...","concept":"...","visual_identity":"...","scenes":[{"description":"...","prompt":"...","transition":"..."}]}]}. Crée EXACTEMENT 3 propositions RADICALEMENT différentes, chacune avec EXACTEMENT le nombre de scènes demandé. Ne recopie pas les mots du brief : développe une véritable dramaturgie visuelle, des actions concrètes et originales, des plans variés, un mouvement de caméra, lumière, cadrage, continuité spatiale et temporelle. Chaque prompt est AUTONOME, prêt à coller dans LoreMotion, en anglais clair, indique sujet, action, mouvement, caméra, décor, durée, et contraintes de cohérence. Ne réclame pas de texte visible dans les vidéos. Si continuité demandée, assure une progression causale explicite, identité et vêtements stables, et des raccords compatibles entre scènes. Si paroles fournies, synchronise l'intention et la progression des scènes aux paroles sans les illustrer littéralement à chaque fois. Si analyse audio présente, utilise les variations d'énergie et les changements mesurés comme indices sans inventer de BPM. Évite clichés, répétitions, images génériques. Chaque proposition doit être complète, et chaque scène doit comporter description, prompt et transition. Brief JSON :\n'''+json.dumps(brief,ensure_ascii=False)
    data=gemini(prompt,16000)
    proposals=data.get('proposals',[])
    if len(proposals)<2:raise RuntimeError('Gemini n’a pas renvoyé plusieurs scénarios. Réessaie.')
    n=int(s.kc_scene_count)
    for p in proposals:
        if len(p.get('scenes',[]))!=n:raise RuntimeError('Le nombre de scènes renvoyé est incorrect. Réessaie.')
        for scene in p['scenes']:
            if not scene.get('prompt'):raise RuntimeError('Un prompt de scène manque. Réessaie.')
    return proposals

def change_scene(scene, direction):
    brief={'original':scene,'instruction':direction,'whole_story':[{'description':x.get('description',''),'prompt':x.get('prompt','')} for x in s.kc_scenes], 'duration':s.kc_scene_seconds,'continuity':s.kc_continuity}
    data=gemini('''Réécris UNE scène de clip, avec inventivité, sans modifier les autres. Respecte le raccord narratif avec les scènes voisines. Retourne UNIQUEMENT JSON {"description":"...","prompt":"...","transition":"..."}. Prompt vidéo en anglais précis prêt pour LoreMotion. Données : '''+json.dumps(brief,ensure_ascii=False),3500)
    if not data.get('prompt'):raise RuntimeError('Prompt manquant dans la réponse.')
    return data


def chatgpt_request(kind='scenarios'):
    brief=creative_brief()
    if kind=='image':
        return ('Crée directement une image pour mon clip, format '+s.kc_format+
                ', style '+s.kc_style+'. Idée : '+s.kc_idea+
                '. Je l’importerai ensuite dans KarmaClip.')
    return (
        'Tu es le réalisateur créatif de mon clip KarmaClip. '
        'Écris des prompts vidéo précis en anglais, originaux et sans clichés. '
        'Réponds UNIQUEMENT en JSON valide, sans balises Markdown, au format : '
        '{"title":"Titre","concept":"Concept","visual_identity":"Direction artistique",'
        '"scenes":[{"description":"Description française","prompt":"English video prompt with camera and action",'
        '"transition":"Raccord"}]}. '
        'Produis exactement '+str(brief['number_of_scenes'])+' scènes de '+
        str(brief['seconds_per_scene'])+' secondes. Brief : '+
        json.dumps(brief,ensure_ascii=False)
    )

def import_chatgpt_scenario(raw):
    cleaned=raw.strip()
    if cleaned.startswith('```'):
        cleaned=cleaned.split('\n',1)[-1]
        if cleaned.rstrip().endswith('```'):
            cleaned=cleaned.rstrip()[:-3].strip()
    data=json.loads(cleaned)
    if isinstance(data,dict) and 'proposals' in data:
        choices=data['proposals']
        if not isinstance(choices,list) or not choices:
            raise ValueError('Aucun scénario trouvé.')
        data=choices[0]
    scenes=data.get('scenes') if isinstance(data,dict) else data
    if not isinstance(scenes,list) or not 1<=len(scenes)<=60:
        raise ValueError('Il faut entre 1 et 60 scènes.')
    validated=[]
    for i,sc in enumerate(scenes):
        if not isinstance(sc,dict) or not isinstance(sc.get('prompt'),str) or not sc['prompt'].strip():
            raise ValueError(f'Prompt manquant pour la scène {i+1}.')
        validated.append({'id':i+1,'description':str(sc.get('description','')),
                          'prompt':sc['prompt'].strip(),'transition':str(sc.get('transition','')),
                          'locked':False,'revision':0})
    return validated

def png(im):
    b=io.BytesIO();im.convert('RGB').save(b,format='PNG');return b.getvalue()

def export_project():
    data={k:s.get('kc_'+k) for k in DEFAULT if k not in ('image','music','clips','final')}
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',json.dumps(data,ensure_ascii=False,indent=2))
        if s.kc_image:z.writestr('image.png',s.kc_image)
        if s.kc_music:z.writestr('music'+Path(s.kc_music_name).suffix,s.kc_music)
        # Clips intentionally excluded to avoid very large ZIPs.
    return b.getvalue()

def restore_project(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        data=json.loads(z.read('project.json'))
        for k,v in DEFAULT.items():
            if k in data and k not in ('image','music','clips','final') and isinstance(data[k],type(v)):
                s['kc_'+k]=data[k]
        if 'image.png' in z.namelist():s.kc_image=z.read('image.png')
        for name in z.namelist():
            if name.startswith('music.'):
                s.kc_music=z.read(name);s.kc_music_name=name
    s.kc_final=None

def ff(args,timeout=600):
    p=subprocess.run(['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error',*map(str,args)],capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stderr[-900:] or 'Erreur FFmpeg')

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode:raise RuntimeError('MP4 non reconnu.')
    return float(p.stdout.strip())

def filters(item):
    e=item.get('effect','Aucun');v=float(item.get('intensity',.5));f=[]
    if e=='Noir et blanc':f.append('hue=s=0')
    elif e=='Cinéma':f.append(f'eq=contrast={1+.22*v:.3f}:saturation={1-.12*v:.3f}')
    elif e=='Vintage':f.append(f'eq=saturation={1-.5*v:.3f}:gamma_r={1+.12*v:.3f}:gamma_b={1-.1*v:.3f}')
    elif e=='Couleurs vives':f.append(f'eq=saturation={1+v:.3f}')
    elif e=='Lumineux':f.append(f'eq=brightness={.16*v:.3f}')
    elif e=='Sombre':f.append(f'eq=brightness={-.2*v:.3f}')
    elif e=='Froid':f.append(f'colorbalance=rs={-.2*v:.3f}:bs={.2*v:.3f}')
    elif e=='Chaud':f.append(f'colorbalance=rs={.2*v:.3f}:bs={-.2*v:.3f}')
    elif e=='Flou':f.append(f'boxblur={int(1+6*v)}:1')
    elif e=='Netteté':f.append(f'unsharp=5:5:{.2+v:.2f}')
    elif e=='Vignette':f.append(f'vignette=angle={.2+.4*v:.3f}')
    elif e=='Grain':f.append(f'noise=alls={int(4+24*v)}:allf=t')
    elif e=='Miroir':f.append('hflip')
    if item.get('mirror') and e!='Miroir':f.append('hflip')
    return f

def clip_disk_path(ident):
    root=Path(tempfile.gettempdir())/'karmaclip_media'
    root.mkdir(parents=True,exist_ok=True)
    return root/(ident+'.mp4')

def cleanup_clip(ident):
    clip_disk_path(ident).unlink(missing_ok=True)

def montage():
    """Export à faible mémoire: un seul processus FFmpeg par plan, concat sans réencodage."""
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFmpeg et FFprobe sont nécessaires pour exporter.')
    quality=s.get('kc_export_quality','720p')
    long_edge=1280 if quality=='720p' else 1920 if quality=='1080p' else 854
    ratio={'9:16':(9,16),'1:1':(1,1),'16:9':(16,9)}[s.kc_format]
    if ratio==(1,1):size=(long_edge,long_edge)
    elif ratio==(9,16):size=(int(long_edge*9/16)//2*2,long_edge)
    else:size=(long_edge,int(long_edge*9/16)//2*2)
    crf=int(s.get('kc_export_crf',29))
    with tempfile.TemporaryDirectory(prefix='karmamontage_') as d:
        root=Path(d);segs=[];total=0.0
        for i,key in enumerate(s.kc_order):
            item=s.kc_clips[key]
            src=Path(item['path'])
            if not src.is_file():
                raise RuntimeError('Vidéo temporaire introuvable. Réimporte tes MP4 après le redémarrage du serveur.')
            duration=probe(src)
            start=max(0.,float(item['start']));end=min(float(item['end']),duration)
            speed=float(item['speed'])
            if end-start<.2 or speed<=0:raise RuntimeError(f'Découpe invalide pour la séquence {i+1}.')
            segment_duration=(end-start)/speed
            total+=segment_duration
            # Limiter threads, images en attente et fréquence d'images évite les pics RAM.
            vf=f'scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,setpts=(PTS-STARTPTS)/{speed}'
            fx=filters(item)
            if fx:vf+=','+','.join(fx)
            fade=max(0.,min(float(item.get('fade',0)),segment_duration/2-.02))
            if fade>.01:vf+=f',fade=t=in:st=0:d={fade:.3f},fade=t=out:st={segment_duration-fade:.3f}:d={fade:.3f}'
            vf+=',format=yuv420p'
            out=root/f'part{i:03}.mp4'
            ff(['-threads','1','-filter_threads','1','-ss',start,'-i',src,'-t',end-start,
                '-vf',vf,'-an','-c:v','libx264','-threads','1','-preset','ultrafast',
                '-crf',crf,'-max_muxing_queue_size','64','-movflags','+faststart',out],timeout=300)
            segs.append(out)
        manifest=root/'files.txt'
        manifest.write_text(''.join(f"file '{p.name}'\n" for p in segs),encoding='utf-8')
        joined=root/'joined.mp4'
        ff(['-threads','1','-f','concat','-safe','0','-i',manifest,'-c','copy','-movflags','+faststart',joined],timeout=120)
        tracks=[]
        for label,blob,name,volume in [('musique',s.kc_music,s.kc_music_name,s.get('kc_music_volume',1.)),
                                        ('voix',s.get('kc_voice'),s.get('kc_voice_name','voix.wav'),s.get('kc_voice_volume',1.))]:
            if blob and float(volume)>0:
                suffix=Path(name).suffix.lower()
                if suffix not in ('.wav','.mp3','.m4a','.aac','.ogg'):suffix='.wav'
                target=root/(label+suffix);target.write_bytes(blob)
                tracks.append((target,float(volume)))
        if not tracks:
            target=clip_disk_path('export_'+hashlib.sha256(os.urandom(16)).hexdigest())
            shutil.copyfile(joined,target)
            return str(target)
        args=['-threads','1','-i',joined]
        for target,_ in tracks:args+=['-i',target]
        graph=[]
        for i,(_,vol) in enumerate(tracks,1):
            graph.append(f'[{i}:a]aresample=44100,volume={vol:.3f},apad,atrim=duration={total:.3f},asetpts=PTS-STARTPTS[a{i}]')
        if len(tracks)==1:graph.append('[a1]anull[aout]')
        else:graph.append(''.join(f'[a{i}]' for i in range(1,len(tracks)+1))+f'amix=inputs={len(tracks)}:duration=longest:normalize=0[aout]')
        out=root/'final.mp4'
        ff(args+['-filter_complex',';'.join(graph),'-map','0:v:0','-map','[aout]',
            '-c:v','copy','-c:a','aac','-b:a','128k','-t',total,'-movflags','+faststart',out],timeout=180)
        target=clip_disk_path('export_'+hashlib.sha256(os.urandom(16)).hexdigest())
        shutil.copyfile(out,target)
        return str(target)

st.markdown('<div class="kc-hero"><div class="kc-hero-title">🎬 KarmaClip Studio</div><div class="kc-hero-sub">De ton idée au clip final ✨ · Crée, imagine, anime et monte — à ton rythme.</div></div>',unsafe_allow_html=True)
st.caption('Ton image → une vraie histoire IA → LoreMotion → ton montage')
with st.expander('📁 Projet et sauvegarde'):
    s.kc_name=st.text_input('Nom du projet',value=s.kc_name)
    st.download_button('💾 Sauvegarder le projet',export_project(),file_name='KarmaClip_projet.zip',mime='application/zip',use_container_width=True)
    backup=st.file_uploader('Restaurer un projet',type=['zip'])
    if backup and st.button('Restaurer ce projet'):
        try:restore_project(backup.getvalue());st.success('Projet restauré');st.rerun()
        except Exception as e:st.error(str(e))
    st.caption('Les MP4 volumineux ne sont pas inclus dans le ZIP. Garde-les sur ton téléphone.')
step=st.radio('Parcours',list(range(4)),format_func=lambda i:STEPS[i],index=s.kc_step,horizontal=True,label_visibility='collapsed')
s.kc_step=step
st.markdown(f'<div class="kc-progress">✨ Étape {step+1} sur 4 · {["Donne vie à ton image","Imagine ton histoire","Anime tes scènes","Assemble ton film"][step]}</div>',unsafe_allow_html=True)
st.divider()

if step==0:
    st.header('1 · Créer mon image')
    st.write('Décris ton idée. Tu peux importer une image, la retoucher et la conserver comme référence pour ton clip.')
    st.text_area('Quelques mots ou une idée',key='kc_idea',height=100,placeholder='Un tigre traverse une ville endormie…')
    a,b=st.columns(2)
    with a:st.selectbox('Style',['Cinématographique','Photoréaliste','Anime / manga','Surréaliste','Fantastique','Vintage','Illustration','Noir et blanc'],key='kc_style')
    with b:st.selectbox('Format',['9:16','1:1','16:9'],key='kc_format')
    if st.button('✨ Imaginer un concept d’image avec Gemini',use_container_width=True):
        try:
            with st.spinner('Gemini imagine ton image…'):
                d=gemini('Propose un prompt image créatif, détaillé et visuellement original en anglais, fidèle au sujet. JSON uniquement {"prompt":"..."}. Sujet: '+s.kc_idea+' Style: '+s.kc_style+' Ratio: '+s.kc_format,1800)
                s.kc_image_idea=d['prompt']
        except Exception as e:st.error(str(e))
    if s.get('kc_image_idea'):st.text_area('Prompt image à copier dans un générateur',key='kc_image_idea',height=150)
    st.markdown('#### 💬 Créer mon image avec ChatGPT')
    st.code(chatgpt_request('image'),language=None)
    st.link_button('💬 Ouvrir ChatGPT pour créer mon image','https://chatgpt.com/',use_container_width=True)
    st.caption('Copie cette demande dans ChatGPT, génère ton image, puis importe-la ci-dessous.')
    up=st.file_uploader('Importer une photo ou une image',type=['png','jpg','jpeg','webp'],key='image_upload')
    if up:
        try:
            with Image.open(io.BytesIO(up.getvalue())) as im:img=ImageOps.exif_transpose(im).convert('RGB')
            with st.expander('🎛️ Retouches',expanded=True):
                bright=st.slider('Luminosité',.2,2.,1.,.1);contrast=st.slider('Contraste',.2,2.,1.,.1);sat=st.slider('Saturation',0.,2.,1.,.1)
                crop=st.checkbox('Adapter le cadrage au format',value=True)
            img=ImageEnhance.Brightness(img).enhance(bright);img=ImageEnhance.Contrast(img).enhance(contrast);img=ImageEnhance.Color(img).enhance(sat)
            if crop:
                w,h={'9:16':(1080,1920),'1:1':(3000,3000),'16:9':(1920,1080)}[s.kc_format]
                img=ImageOps.fit(img,(w,h),method=Image.Resampling.LANCZOS)
            st.image(img,use_container_width=True);raw=png(img)
            st.download_button('⬇️ Télécharger cette image',raw,'KarmaClip_image.png','image/png',use_container_width=True)
            if st.button('✅ Utiliser cette image pour le clip',type='primary',use_container_width=True):s.kc_image=raw;st.success('Image conservée.')
        except Exception as e:st.error(str(e))
    if s.kc_image:st.image(s.kc_image,caption='Image de référence conservée',width=200)
    if st.button('Continuer vers le scénario →',type='primary',use_container_width=True):s.kc_step=1;st.rerun()

elif step==1:
    st.header('2 · Imaginer mon clip')
    st.text_area('Ton idée, même en trois mots',key='kc_idea',height=90)
    st.text_area('Paroles de la chanson (facultatif)',key='kc_lyrics',height=140)
    audio=st.file_uploader('Musique MP3, WAV ou M4A (facultatif)',type=['mp3','wav','m4a'],key='music_upload')
    if audio:
        raw=audio.getvalue();digest=hashlib.sha256(raw).hexdigest()
        if s.get('kc_music_digest')!=digest:
            s.kc_music=raw;s.kc_music_name=audio.name;s.kc_music_digest=digest;s.kc_audio_report=None
        st.audio(raw)
    if s.kc_music:
        if st.button('🎵 Analyser la musique',use_container_width=True):
            try:
                with st.spinner('Analyse de la durée et des variations d’énergie…'):s.kc_audio_report=audio_analysis(s.kc_music,s.kc_music_name)
            except Exception as e:st.error(str(e))
        if s.kc_audio_report:
            st.write('Durée :',s.kc_audio_report.get('duration'),'secondes')
            st.caption(s.kc_audio_report.get('note',''))
            if s.kc_audio_report.get('energy'):st.line_chart(s.kc_audio_report['energy'])
    a,b=st.columns(2)
    with a:st.number_input('Nombre de scènes',min_value=1,max_value=60,key='kc_scene_count')
    with b:st.selectbox('Durée par scène (secondes)',[3,4,5,6,8,10],key='kc_scene_seconds')
    st.checkbox('Histoire continue : mêmes personnages, décors et raccords',key='kc_continuity')
    if st.button('✨ Créer 3 scénarios vraiment différents',type='primary',use_container_width=True):
        if not s.kc_idea.strip() and not s.kc_lyrics.strip():st.warning('Écris quelques mots ou ajoute des paroles.')
        else:
            try:
                s.kc_project_seed+=1
                with st.spinner('Gemini construit trois réalisations complètes…'):
                    s.kc_proposals=new_proposals();s.kc_chosen=0
                st.success('Trois propositions créées !')
            except Exception as e:
                st.warning('Gemini indisponible : continue avec ChatGPT ou en manuel ci-dessous.')
                st.caption(str(e))
    st.markdown('### 💬 Secours ChatGPT — ou création directe')
    st.caption('Copie la demande dans ChatGPT, puis colle sa réponse JSON ici en une seule fois.')
    st.code(chatgpt_request(),language=None)
    st.link_button('💬 Continuer avec ChatGPT','https://chatgpt.com/',use_container_width=True)
    imported=st.text_area('📋 Coller le scénario JSON complet de ChatGPT',height=160,key='kc_chatgpt_import',
                          placeholder='{"title":"Mon clip","scenes":[{"description":"...","prompt":"...","transition":"..."}]}')
    if st.button('✅ Importer toutes les scènes ChatGPT',use_container_width=True):
        try:
            scenes=import_chatgpt_scenario(imported)
            s.kc_scenes=scenes
            s.kc_proposals=[]
            st.success(f'{len(scenes)} scènes importées !')
            st.rerun()
        except (ValueError,TypeError) as e:
            st.error(f'Import impossible : {e}. Colle le JSON complet donné par ChatGPT.')
    with st.expander('✍️ Mode manuel — sans aucune IA'):
        manual_description=st.text_area('Description de la scène',key='kc_manual_description')
        manual_prompt=st.text_area('Prompt vidéo',key='kc_manual_prompt')
        if st.button('➕ Ajouter cette scène manuellement',use_container_width=True):
            if not manual_prompt.strip():
                st.warning('Ajoute au moins un prompt vidéo.')
            else:
                ident=max((x.get('id',0) for x in s.kc_scenes),default=0)+1
                s.kc_scenes.append({'id':ident,'description':manual_description,'prompt':manual_prompt,
                                    'transition':'','locked':False,'revision':0})
                st.rerun()
    if s.kc_proposals:
        labels=[f'{i+1}. {p.get("title","Proposition")}' for i,p in enumerate(s.kc_proposals)]
        chosen=st.radio('Choisis ton scénario',list(range(len(labels))),format_func=lambda i:labels[i],key='kc_chosen')
        p=s.kc_proposals[chosen]
        st.write('**Concept :**',p.get('concept',''));st.write('**Identité visuelle :**',p.get('visual_identity',''))
        for i,sc in enumerate(p.get('scenes',[])):
            with st.expander(f'Scène {i+1} — {sc.get("description","")[:75]}'):
                st.write(sc.get('description',''));st.code(sc.get('prompt',''),language=None)
        if st.button('✅ Utiliser ce scénario et modifier les scènes',type='primary',use_container_width=True):
            s.kc_scenes=[dict(x,id=i+1,locked=False,revision=s.kc_project_seed) for i,x in enumerate(p['scenes'])];st.rerun()
    if s.kc_scenes:
        st.subheader('🎞️ Mes scènes modifiables')
        for i,sc in enumerate(s.kc_scenes):
            ident=sc['id'];rev=sc.get('revision',0)
            with st.container(border=True):
                st.markdown(f'**Scène {i+1} · {s.kc_scene_seconds} s**'+(' 🔒' if sc.get('locked') else ''))
                sc['description']=st.text_area('Description',value=sc.get('description',''),key=f'desc_{ident}_{rev}')
                sc['prompt']=st.text_area('Prompt LoreMotion (modifiable)',value=sc.get('prompt',''),height=150,key=f'prompt_{ident}_{rev}')
                sc['locked']=st.checkbox('Verrouiller',value=sc.get('locked',False),key=f'lock_{ident}')
                instruction=st.text_input('Demander un changement à Gemini',key=f'instr_{ident}',placeholder='Plus étrange, changer le décor, autre mouvement…')
                if st.button('✨ Régénérer cette scène seulement',key=f'regen_{ident}',disabled=sc['locked'],use_container_width=True):
                    try:
                        with st.spinner('Réécriture de la scène…'):
                            updated=change_scene(sc,instruction or 'Propose une mise en scène plus originale et visuelle')
                        sc.update(updated)
                        sc['revision']=rev+1;st.rerun()
                    except Exception as e:st.error(str(e))
                a,b,c=st.columns(3)
                with a:
                    if st.button('⬆️',key=f'up_{ident}',disabled=i==0):s.kc_scenes[i-1],s.kc_scenes[i]=s.kc_scenes[i],s.kc_scenes[i-1];st.rerun()
                with b:
                    if st.button('⬇️',key=f'down_{ident}',disabled=i==len(s.kc_scenes)-1):s.kc_scenes[i+1],s.kc_scenes[i]=s.kc_scenes[i],s.kc_scenes[i+1];st.rerun()
                with c:
                    if st.button('🗑️',key=f'del_{ident}'):s.kc_scenes.pop(i);st.rerun()
        if st.button('➕ Ajouter une scène'):
            ident=max((x['id'] for x in s.kc_scenes),default=0)+1;s.kc_scenes.append({'id':ident,'description':'','prompt':'','transition':'','locked':False});st.rerun()
        if st.button('Continuer vers LoreMotion →',type='primary',use_container_width=True):s.kc_step=2;st.rerun()

elif step==2:
    st.header('3 · Générer mes vidéos')
    st.caption('LoreMotion par défaut. Copie le prompt, puis importe l’image de référence sur le site si nécessaire.')
    st.selectbox('Moteur vidéo',list(ENGINES),key='kc_engine')
    st.link_button('🚀 Ouvrir '+s.kc_engine,ENGINES[s.kc_engine],use_container_width=True)
    if s.kc_image:
        st.image(s.kc_image,width=230)
        st.download_button('⬇️ Image de référence',s.kc_image,'KarmaClip_reference.png','image/png',use_container_width=True)
    if not s.kc_scenes:st.info('Crée ton storyboard à l’étape 2.')
    for i,sc in enumerate(s.kc_scenes):
        with st.expander(f'Scène {i+1} · {s.kc_scene_seconds} secondes',expanded=i==0):
            st.write(sc.get('description',''));st.code(sc.get('prompt',''),language=None)
            st.caption('Appuie sur le code pour le copier. Le site externe ne reçoit pas automatiquement le prompt.')
    if st.button('Mes vidéos sont prêtes → Montage',type='primary',use_container_width=True):s.kc_step=3;st.rerun()

else:
    st.header('4 · Atelier de montage')
    st.caption('Importe tes MP4, arrange les plans, règle chaque séquence, ajoute musique et voix, puis exporte.')
    uploads=st.file_uploader('📥 Ajouter des vidéos MP4',type=['mp4'],accept_multiple_files=True,key='video_upload')
    if uploads:
        for up in uploads:
            ident=hashlib.sha256((up.name+':'+str(up.size)).encode()).hexdigest()
            if ident not in s.kc_clips:
                target=clip_disk_path(ident)
                with target.open('wb') as dst:
                    up.seek(0)
                    shutil.copyfileobj(up,dst,1024*1024)
                up.seek(0)
                dur=5.
                if shutil.which('ffprobe'):
                    try:
                        dur=probe(target)
                    except Exception:pass
                s.kc_clips[ident]={'name':up.name,'path':str(target),'start':0.,'end':round(dur,2),'speed':1.,'effect':'Aucun','intensity':.5,'fade':0.,'mirror':False}
                s.kc_order.append(ident)
    if s.kc_order:
        total=sum(max(0.,float(s.kc_clips[k]['end'])-float(s.kc_clips[k]['start']))/max(.1,float(s.kc_clips[k]['speed'])) for k in s.kc_order)
        st.metric('🎬 Durée du film',f'{int(total//60)} min {int(total%60):02d} s')
        st.markdown('**Ordre des séquences**')
        for i,key in enumerate(s.kc_order):
            item=s.kc_clips[key]
            with st.expander(f'{i+1:02d} · {item["name"]} · {(float(item["end"])-float(item["start"]))/float(item["speed"]):.1f} s',expanded=i==0):
                st.video(item['path'])
                a,b=st.columns(2)
                with a:item['start']=st.number_input('Début (secondes)',min_value=0.,value=float(item['start']),step=.1,key=f'start_{key}')
                with b:item['end']=st.number_input('Fin (secondes)',min_value=.2,value=float(item['end']),step=.1,key=f'end_{key}')
                item['speed']=st.select_slider('Vitesse',options=[.25,.5,.75,1.,1.25,1.5,2.,3.,4.],value=float(item['speed']),key=f'speed_{key}')
                effects=['Aucun','Cinéma','Vintage','Noir et blanc','Couleurs vives','Lumineux','Sombre','Froid','Chaud','Flou','Netteté','Vignette','Grain','Miroir']
                item['effect']=st.selectbox('Effet',effects,index=effects.index(item['effect']) if item['effect'] in effects else 0,key=f'effect_{key}')
                item['intensity']=st.slider('Intensité de l’effet',0.,1.,float(item['intensity']),.1,key=f'intensity_{key}')
                item['fade']=st.select_slider('Fondu noir en entrée et sortie',options=[0.,.2,.4,.6,1.],value=float(item['fade']),key=f'fade_{key}')
                item['mirror']=st.checkbox('Miroir horizontal',value=bool(item['mirror']),key=f'mirror_{key}')
                a,b,c=st.columns(3)
                with a:
                    if st.button('⬆️ Monter',key=f'cu_{key}',disabled=i==0,use_container_width=True):s.kc_order[i-1],s.kc_order[i]=s.kc_order[i],s.kc_order[i-1];s.kc_final=None;st.rerun()
                with b:
                    if st.button('⬇️ Descendre',key=f'cd_{key}',disabled=i==len(s.kc_order)-1,use_container_width=True):s.kc_order[i+1],s.kc_order[i]=s.kc_order[i],s.kc_order[i+1];s.kc_final=None;st.rerun()
                with c:
                    if st.button('🗑️ Retirer',key=f'cx_{key}',use_container_width=True):s.kc_order.pop(i);s.kc_clips.pop(key,None);cleanup_clip(key);s.kc_final=None;st.rerun()
    st.markdown('### 🎧 Audio')
    music=st.file_uploader('Musique de fond (MP3, WAV, M4A)',type=['mp3','wav','m4a'],key='montage_audio')
    if music:s.kc_music=music.getvalue();s.kc_music_name=music.name
    if s.kc_music:
        st.audio(s.kc_music)
        s.kc_music_volume=st.slider('Volume musique',0.,2.,float(s.get('kc_music_volume',1.)),.1)
        if st.button('Supprimer la musique du montage'):s.kc_music=None;st.rerun()
    voice=st.file_uploader('Voix off séparée (MP3, WAV, M4A)',type=['mp3','wav','m4a'],key='voice_upload')
    if voice:s.kc_voice=voice.getvalue();s.kc_voice_name=voice.name
    if s.get('kc_voice'):
        st.audio(s.kc_voice)
        s.kc_voice_volume=st.slider('Volume voix',0.,2.,float(s.get('kc_voice_volume',1.)),.1)
        if st.button('Supprimer la voix off'):s.kc_voice=None;st.rerun()
    st.caption('Les sons des MP4 d’origine sont désactivés. Les pistes audio ajoutées sont mixées et adaptées à la durée du film.')
    st.selectbox('Qualité d’export',['480p','720p','1080p'],key='kc_export_quality',help='720p recommandé pour Render gratuit ; 480p si l’export reste instable.')
    st.caption('Encodage léger : 24 images/s, 1 thread, fichiers sur disque. Les fichiers temporaires disparaissent si Render redémarre.')
    ready=bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    if not ready:st.warning('FFmpeg/FFprobe absents sur Render : installer le Dockerfile avant l’export.')
    if st.button('🎬 Exporter le film MP4',type='primary',use_container_width=True,disabled=not ready or not s.kc_order):
        try:
            with st.spinner('Encodage en cours…'):
                previous=s.kc_final
                s.kc_final=montage()
                if previous and isinstance(previous,str):
                    Path(previous).unlink(missing_ok=True)
            st.success('Film prêt !')
        except Exception as e:st.error(f'Export impossible : {e}')
    if s.kc_final and isinstance(s.kc_final,str) and Path(s.kc_final).exists():
        st.video(s.kc_final)
        with open(s.kc_final,'rb') as output:
            st.download_button('⬇️ Enregistrer le film MP4',output,'KarmaClip_final.mp4','video/mp4',use_container_width=True)
    elif s.kc_final:
        st.warning('Export temporaire perdu après redémarrage. Relance le montage.')
    st.link_button('📱 Ouvrir CapCut sur Android','https://play.google.com/store/apps/details?id=com.lemon.lvoverseas',use_container_width=True)
    st.caption('Après export, enregistre le MP4 sur ton téléphone puis importe-le dans CapCut. Le projet multipiste ne se transfère pas automatiquement.')
    st.caption('Les effets sont visibles après export. Pas encore de timeline tactile, de prévisualisation instantanée des effets ni de transitions animées. Les clips longs peuvent dépasser les limites du serveur gratuit.')

st.divider();st.caption('KarmaClip Studio · Gemini IA · LoreMotion · Montage')
