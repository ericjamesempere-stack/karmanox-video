import streamlit as st
import requests, json

SPACE = "https://cbensimon-wan2-2-fp8da-aoti-preview2.hf.space"

def generate(image, name, prompt):
    s=requests.Session()
    u=s.post(SPACE+"/gradio_api/upload", files={"files":(name,image)}, timeout=90)
    u.raise_for_status()
    path=u.json()[0]
    img={"path":path,"url":SPACE+"/gradio_api/file="+path,"orig_name":name,"meta":{"_type":"gradio.FileData"}}
    data=[img,None,prompt,6,"blurry, distorted anatomy, low quality",3.5,1,1,42,True,6,"UniPCMultistep",3.0,16,False,True]
    q=s.post(SPACE+"/gradio_api/call/generate_video",json={"data":data},timeout=90)
    q.raise_for_status()
    event=q.json()["event_id"]
    with s.get(SPACE+"/gradio_api/call/generate_video/"+event,stream=True,timeout=(30,240)) as r:
        r.raise_for_status()
        current=""
        for line in r.iter_lines(decode_unicode=True):
            if line.startswith("event:"): current=line[6:].strip()
            if line.startswith("data:") and current=="error": raise RuntimeError(line[5:][:300])
            if line.startswith("data:") and current=="complete":
                obj=json.loads(line[5:])
                def find(x):
                    if isinstance(x,dict):
                        if isinstance(x.get("url"),str) and x["url"].startswith("https://"):return x["url"]
                        for v in x.values():
                            z=find(v)
                            if z:return z
                    if isinstance(x,list):
                        for v in x:
                            z=find(v)
                            if z:return z
                url=find(obj)
                if not url or not url.startswith(SPACE):raise RuntimeError("URL vidéo inattendue")
                video=s.get(url,timeout=90)
                video.raise_for_status()
                return video.content
    raise RuntimeError("Le GPU gratuit n'a pas terminé la génération.")

def run():
    st.subheader("🎬 Wan 2.2 — Animation 2D automatique")
    image=st.file_uploader("Ton dessin (PNG/JPG/WEBP, max 8 Mo)",type=["png","jpg","jpeg","webp"],key="wan2_image")
    prompt=st.text_area("Mouvement souhaité",value="The cartoon character dances naturally, moving arms and legs. Preserve original 2D drawing style and face.",key="wan2_prompt")
    if st.button("🎬 Générer avec Wan 2.2",key="wan2_go"):
        if not image:st.warning("Ajoute une image.")
        elif image.size>8*1024*1024:st.error("8 Mo maximum.")
        else:
            try:
                with st.spinner("Génération sur GPU partagé, cela peut prendre plusieurs minutes…"):
                    st.session_state["wan2_result"]=generate(image.getvalue(),image.name,prompt)
            except Exception as e:st.error("Service gratuit indisponible : "+str(e))
    if st.session_state.get("wan2_result"):
        st.video(st.session_state["wan2_result"])
        st.download_button("⬇️ Télécharger le MP4",st.session_state["wan2_result"],"KarmaClip_Wan22.mp4","video/mp4")
    st.link_button("Ouvrir NiftyVid si Wan est indisponible","https://igorcsis.github.io/nifty-vid/")
    st.caption("Basé sur le protocole public de NiftyVid (MIT). Gratuit, mais non garanti ni illimité.")
