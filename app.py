import io, math, json, wave, re, base64
from pathlib import Path
import streamlit as st

st.set_page_config(page_title='KarmaClip AI — Studio', page_icon='🎬', layout='wide')
st.title('🎬 KarmaClip AI — Studio')
st.caption('Analyser → Imaginer → Générer → Monter · Mode manuel, sans automatisation du navigateur')

with st.expander('🧠 Intelligence artificielle : transcription et vision'):
    api_key=st.text_input('Clé API OpenAI (facultative)',type='password',help='Ne jamais publier une clé dans GitHub.')
    st.caption('Les appels à l’API peuvent être payants. La transcription du chant est parfois imparfaite.')

def get_client():
    from openai import OpenAI
    return OpenAI(api_key=api_key, timeout=90)

def transcribe(upload):
    if len(upload.getvalue())>25*1024*1024:
        raise ValueError('Fichier supérieur à 25 Mo : exporter une copie MP3 compressée pour la transcription.')
    f=io.BytesIO(upload.getvalue()); f.name=upload.name
    return get_client().audio.transcriptions.create(model='whisper-1',file=f).text

def inspect_image(upload):
    ext=upload.name.rsplit('.',1)[-1].lower()
    mime={'png':'image/png','webp':'image/webp'}.get(ext,'image/jpeg')
    data=base64.b64encode(upload.getvalue()).decode('ascii')
    res=get_client().chat.completions.create(model='gpt-4.1-mini',messages=[{'role':'system','content':'Décris précisément les éléments VISIBLES de cette image en français. Nombre de personnages, forme, visage, couleurs, vêtements, accessoires, positions, décor, esthétique. N’invente rien. Fournis une fiche de continuité réutilisable pour des prompts de vidéo, sans transformer les personnages.'},{'role':'user','content':[{'type':'text','text':'Crée une fiche d’identité visuelle permanente.'},{'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+data}}]}],max_tokens=850)
    return res.choices[0].message.content

STYLES=['Cinéma réaliste','Danse et chorégraphie','Fête et festival','Clip musical','Comédie','Drame','Romance','Thriller','Science-fiction','Fantastique','Action','Aventure','Documentaire','Animation 3D','Manga','Vintage','Expérimental','Western','Sport','Poétique']
SITES={'LoreMotion':'https://loremotion.com/generate/','Kling AI':'https://klingai.com/','Wan AI':'https://wan.video/','LTX Studio':'https://ltx.studio/','Vidu':'https://www.vidu.com/','CapCut':'https://www.capcut.com/'}

def audio_seconds(upload):
    if upload is None:return None
    raw=upload.getvalue()
    if upload.name.lower().endswith('.wav'):
        try:
            with wave.open(io.BytesIO(raw),'rb') as w:return w.getnframes()/w.getframerate()
        except Exception:pass
    try:
        from mutagen import File
        a=File(io.BytesIO(raw))
        return float(a.info.length) if a and a.info else None
    except Exception:return None

def lines_of(text):
    return [re.sub(r'^\s*\[[^]]+\]\s*','',line).strip() for line in text.splitlines() if line.strip() and not re.match(r'^\s*\[',line)]

def progression(i,n):
    p=(i+.5)/n
    if p<.12:return 'Establish the characters, setting and initial physical situation with a clear introductory action.'
    if p<.3:return 'Introduce a new physical interaction and build on the prior scene; visibly advance the situation.'
    if p<.55:return 'Increase complexity and energy with a distinct new action; make the progression unmistakable.'
    if p<.75:return 'Develop an unexpected but coherent turn, reaction or variation; avoid repeating earlier motions.'
    if p<.91:return 'Build toward the main visual peak with the strongest meaningful action so far.'
    return 'Resolve the ongoing action naturally and create a satisfying visual ending.'

with st.expander('1 · Sources du projet', expanded=True):
    c1,c2=st.columns(2)
    with c1:
        audio=st.file_uploader('Musique WAV / MP3 (facultatif)',type=['wav','mp3'])
        photo=st.file_uploader('Image de référence (facultative)',type=['png','jpg','jpeg','webp'])
        if photo:st.image(photo,caption='Référence visuelle — à joindre aussi au générateur vidéo',width=260)
    with c2:
        description=st.text_area('Idée / description (facultative)',placeholder='Personnages, situation, intention, décor…',height=100)
        lyrics=st.text_area('Paroles ou transcription (facultatives)',placeholder='Colle les paroles pour activer le mode fidèle aux paroles',height=120)

if 'auto_transcription' not in st.session_state:st.session_state.auto_transcription=''
if 'auto_visual' not in st.session_state:st.session_state.auto_visual=''
if audio and st.button('🎤 Transcrire les paroles automatiquement'):
    if not api_key:st.warning('Renseigne une clé API dans Intelligence artificielle.')
    else:
        try:
            with st.spinner('Transcription en cours…'):st.session_state.auto_transcription=transcribe(audio)
        except Exception as e:st.error(f'Transcription impossible : {e}')
if photo and st.button('👁️ Analyser l’image automatiquement'):
    if not api_key:st.warning('Renseigne une clé API dans Intelligence artificielle.')
    else:
        try:
            with st.spinner('Analyse visuelle en cours…'):st.session_state.auto_visual=inspect_image(photo)
        except Exception as e:st.error(f'Analyse impossible : {e}')
transcribed=st.text_area('Paroles reconnues (à vérifier et corriger)',value=st.session_state.auto_transcription,height=110)
visual=st.text_area('Fiche visuelle IA (à vérifier et corriger)',value=st.session_state.auto_visual,height=140)
all_lyrics=lyrics.strip() or transcribed.strip()

with st.expander('2 · Direction artistique',expanded=True):
    style=st.selectbox('Univers visuel',STYLES)
    method=st.radio('Construction des prompts',['Histoire imaginative','Suivre les paroles'],horizontal=True)
    continuity=st.radio('Raccord entre les scènes',['Continuité globale','Tableaux indépendants'],horizontal=True)
    shot=st.selectbox('Durée cible de chaque séquence', [3,4,5,6,8,10,15],index=2)
    identity=st.text_area('Identité des personnages — description à verrouiller',placeholder='Décris précisément les personnages de l’image : silhouettes, visages, couleurs, vêtements, accessoires. Ne rien inventer qui ne soit pas visible.',height=90)
    if photo and not (identity or visual):st.warning('Analyse l’image ou renseigne une fiche visuelle pour verrouiller les personnages.')
    detected=audio_seconds(audio)
    if detected:st.success(f'Durée audio détectée : {detected:.1f} secondes')
    else:st.info('Durée audio non disponible : indique une durée manuelle. La lecture MP3 nécessite mutagen dans requirements.txt.')
    manual=st.number_input('Durée totale si aucun audio lisible (secondes)',min_value=1,max_value=7200,value=180)
    total=detected or float(manual)
    count=math.ceil(total/shot)
    st.write(f'**{count} scènes** prévues pour {total:.1f} secondes, par segments de {shot} secondes maximum.')

st.subheader('3 · Analyse de l’intention')
if 'analysis' not in st.session_state:st.session_state.analysis=''
if st.button('🔍 Analyser les sources',type='primary'):
    sources=[]
    if audio:sources.append(f'morceau audio de {total:.1f} secondes (durée détectée, pas de reconnaissance musicale)')
    if photo:sources.append('image de référence fournie (non analysée visuellement dans cette version)')
    if description:sources.append(f'idée : {description.strip()}')
    if all_lyrics:sources.append('paroles fournies ou transcrites')
    if visual:sources.append('fiche visuelle analysée')
    st.session_state.analysis=('Sources : '+('; '.join(sources) if sources else 'aucune source — création libre')+'\n'
        f'Direction : {style}. Mode : {method}. Raccord : {continuity}. '
        f'Durée : {total:.1f} s, {count} scènes. '
        'Intention à préciser : trajectoire émotionnelle, évolution des actions, dénouement. '
        'Cette synthèse est éditable. La transcription et la vision sont disponibles via les boutons dédiés et une clé API.')
analysis=st.text_area('Synthèse artistique — modifiable avant la génération',value=st.session_state.analysis,height=145)

st.subheader('4 · Storyboard prêt à copier')
st.caption('La transcription et la vision sont intégrées via API ; le générateur de storyboard reste basé sur des règles et sera à enrichir avec un réalisateur IA.')
if method=='Suivre les paroles' and not all_lyrics:st.warning('Ajoute les paroles pour obtenir un suivi fidèle. Un fichier audio seul ne permet pas ici de transcrire les paroles.')
if st.button('🎞️ Générer tous les prompts'):
    words=lines_of(all_lyrics)
    prompts=[]
    base=(description.strip() or 'Create a coherent original visual narrative based on the chosen direction.')
    for i in range(count):
        start=i*shot; end=min(total,(i+1)*shot)
        lyric_part=''
        if method=='Suivre les paroles' and words:
            lo=int(i*len(words)/count);hi=max(lo+1,int((i+1)*len(words)/count))
            lyric_part='Lyric meaning for this moment: '+ ' / '.join(words[lo:hi])+'. Interpret these words visually, without showing subtitles. '
        scene=(f'SCENE {i+1}/{count} | {start:.1f}–{end:.1f} seconds\n'
          f'Visual direction: {style}. Original concept: {base}. '
          f'{lyric_part}Narrative instruction: {progression(i,count)} '
          f'Unique beat: scene {i+1} must show a distinct purposeful action and a new reaction or change of spatial arrangement. '
          f'Continuity: {"Preserve the established characters, environment and physical cause-and-effect from the previous scene; start from its last pose." if continuity=="Continuité globale" else "This shot can change environment and action; retain the established character identity."} '
          f'Character identity: {(identity or visual).strip() if (identity or visual).strip() else "Match the supplied reference image exactly; do not redesign the subject or introduce a different character style."} '
          'Precise coherent body movement, natural anatomy for the original subject, intentional framing and lighting. '
          'No visual redesign, no character replacement, no text, no subtitles. '
          'The next shot should be able to follow this one naturally.' )
        prompts.append({'scene':i+1,'start':round(start,2),'end':round(end,2),'prompt':scene})
    st.session_state.prompts=prompts

prompts=st.session_state.get('prompts',[])
if prompts:
    for item in prompts:
        with st.expander(f"Scène {item['scene']} · {item['start']:g}–{item['end']:g} s",expanded=item['scene']==1):
            st.code(item['prompt'],language=None)
            st.caption('Copie le texte ci-dessus, puis joins l’image de référence sur LoreMotion.')
    st.download_button('⬇️ Télécharger tous les prompts (.txt)',data='\n\n'.join(x['prompt'] for x in prompts),file_name='karmaclip_prompts.txt',mime='text/plain')
    st.download_button('⬇️ Télécharger le storyboard (.json)',data=json.dumps(prompts,ensure_ascii=False,indent=2),file_name='karmaclip_storyboard.json',mime='application/json')

st.subheader('5 · Générer et monter')
st.write('Génération manuelle : copie le prompt et joins l’image dans le service choisi. Les liens ouvrent les plateformes ; ils ne transmettent pas automatiquement les fichiers.')
for name,url in SITES.items():
    st.markdown(f'**[{name}]({url})**'+(' — priorité' if name=='LoreMotion' else ' — montage' if name=='CapCut' else ' — alternative'))
st.caption('La durée du dernier segment est un repère de montage : le moteur vidéo peut imposer une durée fixe. Ajuste la dernière vidéo dans CapCut.')
