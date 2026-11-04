import os, io, re, json, math, wave, base64, requests
import streamlit as st
from mutagen import File as AudioFile

st.set_page_config(page_title='KarmaClip Agent IA', page_icon='🎬', layout='centered')
st.title('🎬 KarmaClip Agent IA')
st.caption('Réalisateur IA · identité visuelle verrouillée · prompts courts pour LoreMotion')

def secret(name):
    try: return str(st.secrets.get(name, os.environ.get(name, ''))).strip()
    except Exception: return os.environ.get(name, '').strip()

def audio_length(file):
    if not file: return None
    try:
        data=file.getvalue()
        if file.name.lower().endswith('.wav'):
            with wave.open(io.BytesIO(data)) as f: return f.getnframes()/f.getframerate()
        sound=AudioFile(io.BytesIO(data))
        return float(sound.info.length) if sound and sound.info else None
    except Exception: return None

SYSTEM='''You are a music-video director writing short, actionable prompts for an image-to-video generator (LoreMotion). Return ONLY valid JSON with keys: title, synopsis, direction, style, visual_identity, proposals (array of 3 objects with title,pitch), scenes (array of EXACTLY requested scene count; each object has action in French and prompt in English). Make a coherent story with beginning, development and ending. For each prompt use 1 primary visible action, who moves, direction of motion, simple camera instruction, and continuity. Keep each English prompt 35-75 words. No subtitles or on-screen text. No abstract metaphor or conflicting actions. If task_mode is ANIMATE_EXISTING_IMAGE: the uploaded image is the literal first frame, NOT a loose inspiration. Describe ONLY animation of the depicted subjects, with one feasible movement per scene and minimal camera movement. Do not invent new characters or change their appearance. If task_mode is CREATE_NEW_VIDEO: invent an original film from the concept; an optional image may inspire the composition but must not be assumed to be the first frame. If the user supplies an image in animation mode, identify ONLY visible attributes and original medium/style. Preserve original 2D drawing, manga, caricature, 3D render, photo, or mixed-media medium EXACTLY. NEVER humanize a drawn figure or turn a photo into an illustration. Maintain same characters, facial features, body shape, clothing, colors, line work, textures, and proportions across all scenes. Do not invent unseen visual attributes. Do not use 'photorealistic', 'cinematic realism', 'real human', 'realistic anatomy', or 'live-action' unless the input image is demonstrably photographic. If image content cannot be seen, do not claim to have analyzed it. Only music file name and duration are provided, not musical content. Prompt must be usable with the original reference image attached in LoreMotion; never promise exact adherence by the video generator.'''

def chat_call(provider,key,model,content,sys=SYSTEM):
    endpoint={'Groq':'https://api.groq.com/openai/v1/chat/completions','OpenRouter':'https://openrouter.ai/api/v1/chat/completions'}[provider]
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'KarmaClip-Agent/1.1 (Streamlit; music-video storyboard)'}
    if provider=='OpenRouter':headers.update({'HTTP-Referer':'https://karmanox-video.onrender.com','X-Title':'KarmaClip Agent'})
    payload={'model':model,'messages':[{'role':'system','content':sys},{'role':'user','content':content}], 'temperature':0.45,'max_tokens':8192}
    try:
        response=requests.post(endpoint,headers=headers,json=payload,timeout=110)
    except requests.RequestException as e:raise RuntimeError(f'{provider}: connexion impossible ({type(e).__name__})') from e
    if not response.ok:raise RuntimeError(f'{provider} HTTP {response.status_code}: {response.text[:240]}')
    try:return response.json()['choices'][0]['message']['content']
    except (KeyError,IndexError,TypeError,ValueError) as e:raise RuntimeError(f'{provider}: réponse API illisible') from e

def parse_json(raw):
    raw=raw.strip()
    if raw.startswith('```'):raw=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I)
    try:return json.loads(raw)
    except json.JSONDecodeError:
        match=re.search(r'\{.*\}',raw,re.S)
        if match:return json.loads(match.group())
        raise

def valid(result,count):
    scenes=result.get('scenes',[])
    return isinstance(scenes,list) and len(scenes)==count and all(isinstance(s,dict) and s.get('action') and s.get('prompt') for s in scenes)

def build_content(data,photo):
    content=[{'type':'text','text':json.dumps(data,ensure_ascii=False)}]
    if photo:
        if photo.size>3*1024*1024:raise ValueError('Image trop volumineuse : 3 Mo maximum. Compresse-la sans changer son style.')
        mime={'png':'image/png','webp':'image/webp'}.get(photo.name.lower().split('.')[-1],'image/jpeg')
        content.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(photo.getvalue()).decode()}})
    return content

def plan(idea,photo,music,duration,count,mode,direction,style,ratio,task_mode):
    groq=secret('GROQ_API_KEY');router=secret('OPENROUTER_API_KEY')
    if not groq and not router:raise RuntimeError('Ajoute GROQ_API_KEY ou OPENROUTER_API_KEY dans Render > Environment.')
    if task_mode=='Animer une image' and not photo:raise ValueError('Ajoute une image pour le mode animation.')
    data={'task_mode':'ANIMATE_EXISTING_IMAGE' if task_mode=='Animer une image' else 'CREATE_NEW_VIDEO','idee_ou_paroles':idea or 'Inventer une histoire originale avec début, progression et fin', 'nombre_de_scenes':count,'duree_totale_secondes':duration,'duree_par_scene':round(duration/count,2),'mode':mode,'direction':direction if mode=='Manuel' else 'auto','style':style if mode=='Manuel' else 'respecter image si fournie, sinon auto','ratio':ratio,'musique':{'nom':music.name,'duree':audio_length(music)} if music else None,'image_reference':bool(photo),'priorite':('Animer uniquement les sujets de l’image importée; image comme première frame; identité, style et décor inchangés; une seule action physique simple par scène' if task_mode=='Animer une image' else 'Créer une nouvelle vidéo originale; image facultative comme inspiration; une seule action principale par scène')}
    content=build_content(data,photo)
    providers=[]
    if photo:
        # Groq vision model is configurable: unavailable/retired IDs should not be silently substituted.
        if groq and secret('GROQ_VISION_MODEL'):providers.append(('Groq',groq,secret('GROQ_VISION_MODEL')))
        if router:providers.append(('OpenRouter',router,secret('OPENROUTER_VISION_MODEL') or 'openrouter/free'))
        if not providers:raise RuntimeError('Pour une image, configure OPENROUTER_API_KEY (ou GROQ_VISION_MODEL avec un modèle vision actif).')
    else:
        if groq:providers.append(('Groq',groq,secret('GROQ_TEXT_MODEL') or 'llama-3.3-70b-versatile'))
        if router:providers.append(('OpenRouter',router,secret('OPENROUTER_MODEL') or 'openrouter/free'))
    errors=[]
    for provider,key,model in providers:
        try:
            raw=chat_call(provider,key,model,content)
            result=parse_json(raw)
            if not valid(result,count):
                # Retry once with precise JSON correction; do not hallucinate missing scenes locally.
                correction=[{'type':'text','text':json.dumps(data,ensure_ascii=False)+'\nIMPORTANT: Return a complete valid JSON object with EXACTLY '+str(count)+' scenes, each with action and prompt. Keep all visual identity rules. Output JSON only.'}]
                if photo:correction.append(content[1])
                result=parse_json(chat_call(provider,key,model,correction))
            if not valid(result,count):raise ValueError('Storyboard incomplet après une seconde tentative')
            result['provider']=provider;result['model']=model
            return result
        except Exception as e:errors.append(str(e)[:260])
    raise RuntimeError('Échec des fournisseurs : '+' | '.join(errors))

if 'result' not in st.session_state:st.session_state.result=None
st.subheader('1 · Choisis ton objectif')
choice=st.radio('Création vidéo',['Automatique','Créer une vidéo','Animer une image'],horizontal=False,help='Automatique : anime si une image est fournie, sinon crée une nouvelle vidéo.')
st.subheader('2 · Ton point de départ')
idea=st.text_area('Idée, paroles ou description (facultatif)',placeholder='Une histoire, une danse, un personnage…',height=120)
photo=st.file_uploader('Image de référence (facultative)',type=['png','jpg','jpeg','webp'])
if photo:
    st.image(photo,width=230)
task_mode=('Animer une image' if photo else 'Créer une vidéo') if choice=='Automatique' else choice
st.info('🎬 Mode retenu : '+task_mode)
if task_mode=='Animer une image':
    st.caption('🔒 Image = première image de la vidéo. Conserver le dessin ou la photo, ne décrire que le mouvement. Joindre la même image sur LoreMotion en mode image-vers-vidéo.')
else:
    st.caption('✨ Création originale : l’IA invente une vidéo. L’image éventuelle sert d’inspiration, sans obligation de reprendre exactement son personnage.')
music=st.file_uploader('Musique (facultative)',type=['wav','mp3'])
length=audio_length(music)
if length:st.caption(f'Durée musicale détectée : {length:.1f} secondes')
count=st.number_input('Nombre de scènes',min_value=1,max_value=60,value=6,step=1)
source=st.radio('Durée totale',['Selon les scènes','Durée de la musique','Personnalisée'])
per=st.selectbox('Durée indicative par scène',[3.5,5.0,6.0,8.0,10.0],index=1)
custom=st.number_input('Durée personnalisée en secondes',min_value=3.0,max_value=900.0,value=30.0)
duration=float(length if source=='Durée de la musique' and length else custom if source=='Personnalisée' else count*per)
st.caption(f'{int(count)} scènes · {duration:.1f} secondes · environ {duration/count:.1f} s par scène')
st.subheader('3 · Qui dirige ?')
mode=st.radio('Mode',['Automatique','Manuel'],horizontal=True)
direction='';style='';ratio='9:16'
if mode=='Manuel':
    direction=st.selectbox('Type de clip',['story','dance','variety','performance','abstract'])
    style=st.selectbox('Style (si aucune image de référence)',['Libre','Cinéma photoréaliste','Animation 3D','Manga','Vintage','Surréaliste','Documentaire'])
    ratio=st.selectbox('Format',['9:16','16:9','1:1'])
if st.button('🧠 L’agent crée toute mon histoire',type='primary',use_container_width=True):
    if task_mode=='Animer une image' and not photo:st.warning('Ajoute une image pour pouvoir l’animer.')
    elif not (idea.strip() or photo or music):st.warning('Ajoute au moins une idée, une image ou une musique.')
    else:
        try:
            with st.spinner('Le réalisateur IA prépare les séquences LoreMotion…'):
                st.session_state.result=plan(idea.strip(),photo,music,duration,int(count),mode,direction,style,ratio,task_mode)
            st.success('Storyboard IA créé.')
        except Exception as e:st.error(str(e))
result=st.session_state.result
if result:
    st.subheader('4 · Le projet de l’agent')
    st.caption('Mode : '+task_mode)
    st.markdown('**'+str(result.get('title','Mon clip'))+'**')
    st.write(result.get('synopsis',''))
    if result.get('visual_identity'):st.caption('🔒 Identité visuelle : '+str(result['visual_identity']))
    st.caption('Modèle : '+result.get('provider','')+' · '+result.get('model',''))
    for p in result.get('proposals',[]):st.info(str(p.get('title',''))+' — '+str(p.get('pitch','')))
    full=[]
    for i,scene in enumerate(result['scenes']):
        start=duration*i/count;end=duration*(i+1)/count
        with st.expander(f'Scène {i+1} · {start:.1f}–{end:.1f} s',expanded=i==0):
            st.write(scene['action'])
            edited=st.text_area('Prompt LoreMotion (modifiable)',value=scene['prompt'],key=f'prompt_{id(result)}_{i}',height=140)
            full.append(f'SCÈNE {i+1} | {start:.1f}–{end:.1f} s\n{edited}')
    st.download_button('⬇️ Télécharger tous les prompts','\n\n'.join(full),'KarmaClip_LoreMotion_prompts.txt',use_container_width=True)
    st.download_button('⬇️ Télécharger le storyboard JSON',json.dumps(result,ensure_ascii=False,indent=2),'KarmaClip_storyboard.json',use_container_width=True)
    st.link_button('🎥 Ouvrir LoreMotion','https://loremotion.com/',use_container_width=True)
st.divider()
st.caption('En mode animation, importe l’image originale dans LoreMotion en image-vers-vidéo. En création, utilise texte-vers-vidéo ou une image facultative. LoreMotion est ouvert manuellement. Les prompts favorisent la fidélité mais ne garantissent pas le rendu du moteur vidéo. La musique n’est pas transcrite ni analysée : seule sa durée est lue.')
st.divider()
with st.expander('🎨 Atelier animation 2D (nouveau)', expanded=False):
    from studio_2d import run
    run()
