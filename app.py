import os, io, re, json, math, wave, base64, urllib.request, urllib.error
import streamlit as st
from mutagen import File as AudioFile

st.set_page_config(page_title='KarmaClip Agent IA', page_icon='🎬', layout='centered')
st.title('🎬 KarmaClip Agent IA')
st.caption('Un point de départ, un réalisateur IA, un storyboard complet. Mode automatique ou manuel.')

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

def chat_call(provider, key, model, user_content):
    endpoint={'Groq':'https://api.groq.com/openai/v1/chat/completions','OpenRouter':'https://openrouter.ai/api/v1/chat/completions'}[provider]
    payload={'model':model,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':user_content}], 'temperature':0.75,'max_tokens':8192}
    headers={'Content-Type':'application/json','Authorization':'Bearer '+key}
    if provider=='OpenRouter':headers['HTTP-Referer']='https://render.com'
    request=urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request,timeout=110) as response: result=json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{provider} HTTP {e.code}: {e.read(350).decode(errors="replace")}')
    return result['choices'][0]['message']['content']

SYSTEM='''Tu es un réalisateur de clips vidéo expérimenté. Réponds uniquement avec un objet JSON valide, sans Markdown, de forme:
{"title":"titre","synopsis":"histoire originale avec début, progression et fin","direction":"story|dance|variety|performance|abstract","style":"style visuel","proposals":[{"title":"...","pitch":"..."},{"title":"...","pitch":"..."},{"title":"...","pitch":"..."}],"scenes":[{"action":"action narrative concrète en français","prompt":"prompt vidéo détaillé en anglais"}]}
Respecte EXACTEMENT le nombre de scènes. Chaque scène est différente, causale et filmable. Si danse continue: mêmes personnages, positions, mouvements corporels raccordés entre scènes. Si paroles: raconter une histoire liée au sens sans sous-titres. Si image: identité et costume constants, ne pas inventer de détails invisibles. Les prompts incluent mouvement, cadrage, décor, lumière, continuité et action finale. Ne promets pas de génération vidéo. N'invente pas d'analyse sonore: les données musicales ne contiennent que durée et nom de fichier. Évite tout texte à l'image.'''

def parse_json(raw):
    raw=raw.strip()
    if raw.startswith('```'):raw=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I)
    try:return json.loads(raw)
    except json.JSONDecodeError:
        m=re.search(r'\{.*\}',raw,re.S)
        if m:return json.loads(m.group())
        raise

def plan(idea, photo, music, duration, count, mode, direction, style, ratio):
    groq=secret('GROQ_API_KEY');router=secret('OPENROUTER_API_KEY')
    if not groq and not router:raise RuntimeError('Configure GROQ_API_KEY ou OPENROUTER_API_KEY dans Render > Environment.')
    data={'idee_ou_paroles':idea or 'Invente une histoire originale pour un clip, avec une progression visuelle et une conclusion.', 'nombre_de_scenes':count,'duree_totale_secondes':duration,'duree_par_scene':round(duration/count,2),'mode':mode,'direction_imposee':direction if mode=='Manuel' else 'choisir automatiquement','style_impose':style if mode=='Manuel' else 'choisir automatiquement','ratio':ratio,'musique':{'nom':music.name,'duree':audio_length(music)} if music else None,'image_reference':bool(photo)}
    content=[{'type':'text','text':json.dumps(data,ensure_ascii=False)}]
    if photo:
        if photo.size>3*1024*1024:raise ValueError('Image trop volumineuse pour cette version : 3 Mo maximum.')
        ext=photo.name.lower().split('.')[-1]
        mime={'png':'image/png','webp':'image/webp'}.get(ext,'image/jpeg')
        content.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(photo.getvalue()).decode()}})
    errors=[]
    # OpenRouter fallback for text only: its free router may not support vision.
    providers=[]
    if groq:providers.append(('Groq',groq,secret('GROQ_VISION_MODEL') if photo else secret('GROQ_TEXT_MODEL')))
    if router and not photo:providers.append(('OpenRouter',router,secret('OPENROUTER_MODEL') or 'openrouter/free'))
    if photo and not groq:raise RuntimeError('Pour analyser une image, configure une clé Groq et un modèle vision compatible. OpenRouter est réservé au texte dans cette version.')
    for provider,key,model in providers:
        model=model or ('meta-llama/llama-4-scout-17b-16e-instruct' if photo else 'llama-3.3-70b-versatile')
        try:
            result=parse_json(chat_call(provider,key,model,content))
            scenes=result.get('scenes',[])
            if len(scenes)!=count or not all(isinstance(s,dict) and s.get('prompt') and s.get('action') for s in scenes):raise ValueError('Nombre de scènes ou prompts incomplets')
            result['provider']=provider;result['model']=model
            return result
        except Exception as e:errors.append(str(e)[:350])
    raise RuntimeError('Échec des fournisseurs : '+' | '.join(errors))

if 'result' not in st.session_state:st.session_state.result=None
st.subheader('1 · Ton point de départ')
idea=st.text_area('Idée, paroles ou description TikTok (facultatif)',placeholder='Laisse vide si tu préfères fournir uniquement une image ou une musique.',height=130)
photo=st.file_uploader('Image de référence (facultative)',type=['png','jpg','jpeg','webp'])
if photo:st.image(photo,width=230)
music=st.file_uploader('Musique (facultative)',type=['wav','mp3'])
length=audio_length(music)
if length:st.caption(f'Durée musicale détectée : {length:.1f} secondes')
count=st.number_input('Nombre de scènes',min_value=1,max_value=60,value=6,step=1)
source=st.radio('Durée totale', ['Selon les scènes','Durée de la musique','Personnalisée'],horizontal=False)
per=st.selectbox('Durée indicative par scène', [3.5,5.0,6.0,8.0,10.0],index=1)
custom=st.number_input('Durée personnalisée en secondes',min_value=3.0,max_value=900.0,value=30.0)
duration=float(length if source=='Durée de la musique' and length else custom if source=='Personnalisée' else count*per)
st.caption(f'{int(count)} scènes · {duration:.1f} secondes · environ {duration/count:.1f} secondes par scène')
st.subheader('2 · Qui dirige ?')
mode=st.radio('Mode', ['Automatique','Manuel'],horizontal=True)
direction='';style='';ratio='9:16'
if mode=='Manuel':
    direction=st.selectbox('Type de clip',['story','dance','variety','performance','abstract'])
    style=st.selectbox('Style',['Cinéma photoréaliste','Animation 3D','Manga','Vintage','Surréaliste','Documentaire'])
    ratio=st.selectbox('Format',['9:16','16:9','1:1'])
if st.button('🧠 L’agent crée toute mon histoire',type='primary',use_container_width=True):
    if not (idea.strip() or photo or music):st.warning('Ajoute au moins une idée, une image ou une musique.')
    else:
        try:
            with st.spinner('Le réalisateur IA construit ton clip…'):
                st.session_state.result=plan(idea.strip(),photo,music,duration,int(count),mode,direction,style,ratio)
            st.success('Storyboard IA créé.')
        except Exception as e:st.error(str(e))
result=st.session_state.result
if result:
    st.subheader('3 · Le projet de l’agent')
    st.markdown('**'+str(result.get('title','Mon clip'))+'**')
    st.write(result.get('synopsis',''))
    st.caption('Modèle : '+result.get('provider','')+' · '+result.get('model',''))
    for p in result.get('proposals',[]):
        st.info(str(p.get('title',''))+' — '+str(p.get('pitch','')))
    full=[]
    for i,scene in enumerate(result['scenes']):
        start=duration*i/count;end=duration*(i+1)/count
        with st.expander(f'Scène {i+1} · {start:.1f}–{end:.1f} s',expanded=i==0):
            st.write(scene['action'])
            edited=st.text_area('Prompt vidéo (modifiable)',value=scene['prompt'],key=f'prompt_{id(result)}_{i}',height=180)
            full.append(f'SCÈNE {i+1} | {start:.1f}–{end:.1f} s\n{edited}')
    st.download_button('⬇️ Télécharger tous les prompts', '\n\n'.join(full),'KarmaClip_prompts.txt',use_container_width=True)
    st.download_button('⬇️ Télécharger le storyboard JSON',json.dumps(result,ensure_ascii=False,indent=2),'KarmaClip_storyboard.json',use_container_width=True)
    st.link_button('🎥 Ouvrir LoreMotion (génération manuelle)','https://loremotion.com/',use_container_width=True)
st.divider()
st.caption('L’IA est réelle lorsque les clés sont configurées. Les quotas gratuits peuvent changer. Le contenu audio n’est pas écouté ni transcrit : seule la durée est utilisée. Aucune génération vidéo ou montage automatique sur LoreMotion.')
