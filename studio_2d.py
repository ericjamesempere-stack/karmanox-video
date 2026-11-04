"""KarmaClip 2D: animation de calques PNG avec pixels originaux, sans GPU."""
import io, math
from PIL import Image, ImageDraw
import streamlit as st

PARTS = ['Corps','Tête','Bras gauche','Bras droit','Jambe gauche','Jambe droite']
MOTIONS = ['Danse','Marche sur place','Salut','Respiration']

def render_frame(layers, t, motion, size, strength):
    W,H=size
    canvas=Image.new('RGBA',size,(255,255,255,0))
    phase=2*math.pi*t
    for name, layer in layers.items():
        img=layer.copy()
        angle=0.0
        dx=dy=0
        if motion=='Danse':
            dy=int(strength*0.4*math.sin(phase*2))
            dx=int(strength*0.3*math.sin(phase))
            if 'Bras' in name: angle=(1 if 'gauche' in name else -1)*strength*1.1*math.sin(phase)
            if 'Jambe' in name: angle=(1 if 'gauche' in name else -1)*strength*0.5*math.sin(phase)
            if name=='Tête':angle=strength*0.25*math.sin(phase)
        elif motion=='Marche sur place':
            dy=int(strength*0.22*math.sin(phase*2))
            if 'Bras' in name:angle=(1 if 'gauche' in name else -1)*strength*math.sin(phase)
            if 'Jambe' in name:angle=(-1 if 'gauche' in name else 1)*strength*math.sin(phase)
        elif motion=='Salut':
            if name=='Bras droit':angle=-strength*1.7*math.sin(phase)
            if name=='Tête':angle=strength*0.1*math.sin(phase)
        else:
            dy=int(strength*0.12*math.sin(phase))
        if angle:
            img=img.rotate(angle,resample=Image.Resampling.BICUBIC,expand=False)
        canvas.alpha_composite(img,(dx,dy))
    return canvas

def run():
    st.subheader('🎨 Atelier 2D — animation de calques')
    st.info('Animation 2D réelle à partir de calques PNG transparents. Les pixels restent des dessins 2D. Pour plier les coudes ou changer les expressions, il faut davantage de calques/poses : cette version ne les invente pas.')
    st.caption('Importe des PNG transparents de même taille, déjà positionnés sur une toile identique. Le corps est obligatoire ; les autres calques sont facultatifs.')
    layers={}
    uploads={}
    for name in PARTS:
        f=st.file_uploader(name+' (PNG)',type=['png'],key='k2d_'+name)
        if f:uploads[name]=f
    if not uploads:
        st.caption('Prépare ton personnage en plusieurs parties (corps, tête, bras et jambes). Tu peux commencer avec une image entière en « Corps », mais elle ne sera pas articulée.')
    if uploads:
        try:
            for name,f in uploads.items():
                im=Image.open(io.BytesIO(f.getvalue())).convert('RGBA')
                if im.width>1500 or im.height>1500:im.thumbnail((1500,1500))
                layers[name]=im
            size=next(iter(layers.values())).size
            if any(im.size!=size for im in layers.values()):
                st.error('Tous les PNG doivent avoir exactement les mêmes dimensions.')
                return
            if 'Corps' not in layers:
                st.error('Ajoute au minimum le calque Corps.')
                return
        except Exception as exc:
            st.error('Image illisible : '+str(exc));return
        motion=st.selectbox('Mouvement',MOTIONS,key='k2d_motion')
        duration=st.slider('Durée (secondes)',2,8,4,key='k2d_duration')
        fps=st.slider('Images par seconde',6,16,10,key='k2d_fps')
        strength=st.slider('Amplitude du mouvement',3,30,14,key='k2d_strength')
        st.image(render_frame(layers,0.15,motion,size,strength),caption='Aperçu du personnage',width=250)
        if st.button('🎞️ Générer mon animation 2D',type='primary',use_container_width=True,key='k2d_generate'):
            try:
                with st.spinner('Création image par image…'):
                    frames=[]
                    for i in range(duration*fps):
                        rgba=render_frame(layers,(i%fps)/fps,motion,size,strength)
                        bg=Image.new('RGB',size,'white')
                        bg.paste(rgba,mask=rgba.getchannel('A'))
                        frames.append(bg.convert('P',palette=Image.Palette.ADAPTIVE,colors=128))
                    buf=io.BytesIO()
                    frames[0].save(buf,format='GIF',save_all=True,append_images=frames[1:],duration=round(1000/fps),loop=0,optimize=False)
                    st.session_state['k2d_gif']=buf.getvalue()
                st.success('Animation 2D créée sans API ni GPU.')
            except Exception as exc:st.error('Erreur : '+str(exc))
        if st.session_state.get('k2d_gif'):
            st.image(st.session_state['k2d_gif'])
            st.download_button('⬇️ Télécharger mon animation GIF',st.session_state['k2d_gif'],'KarmaClip_animation_2D.gif','image/gif',use_container_width=True)
    st.markdown('**Autres outils 2D :** [Rigby2D](https://rigby2d.com/) · [Stretchy Studio](https://stretchy.studio/) · [Synfig](https://www.synfig.org/) · [OpenToonz](https://opentoonz.github.io/e/)')
    st.markdown('**Vidéo / 3D :** [LoreMotion](https://loremotion.com/) · [ComfyUI](https://www.comfy.org/) · [Blender](https://www.blender.org/)')
    st.caption('Rigby2D et LoreMotion ne sont pas appelés par API : aucune API publique compatible n’a été validée. Les liens servent de solutions externes.')
