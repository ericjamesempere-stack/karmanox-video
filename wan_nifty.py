"""KarmaClip: image -> character preparation -> Wan 2.2 animation.
NiftyVid protocol inspiration; no paid API or account required.
"""
import io
import json
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageOps

SPACE = "https://cbensimon-wan2-2-fp8da-aoti-preview2.hf.space"
MAX_IMAGE = 25 * 1024 * 1024
MAX_PIXELS = 1280

def make_cartoon_body(image_bytes, clothing="#3778a8"):
    """Offline fallback: compose a simple 2D cartoon body beneath a portrait.
    This is NOT AI body generation or faithful character reconstruction.
    """
    src = Image.open(io.BytesIO(image_bytes))
    src = ImageOps.exif_transpose(src).convert("RGBA")
    src.thumbnail((640, 640))
    canvas = Image.new("RGBA", (768, 1152), (245, 243, 239, 255))
    d = ImageDraw.Draw(canvas)
    # Legs, shoes, arms, torso, neck; head is pasted last.
    d.rounded_rectangle((285, 725, 355, 1030), radius=30, fill="#303c50")
    d.rounded_rectangle((415, 725, 485, 1030), radius=30, fill="#303c50")
    d.ellipse((258, 1005, 370, 1065), fill="#252525")
    d.ellipse((400, 1005, 512, 1065), fill="#252525")
    d.line([(280, 510), (185, 705)], fill=clothing, width=75)
    d.line([(490, 510), (580, 705)], fill=clothing, width=75)
    d.ellipse((150, 680, 215, 748), fill="#d5a88b")
    d.ellipse((550, 680, 615, 748), fill="#d5a88b")
    d.rounded_rectangle((270, 430, 500, 765), radius=68, fill=clothing)
    d.rounded_rectangle((357, 380, 411, 465), radius=15, fill="#d5a88b")
    # The uploaded image is placed as a rectangular portrait: no face segmentation.
    head = ImageOps.contain(src, (350, 380))
    backing = Image.new("RGBA", (370, 400), "white")
    backing.alpha_composite(head, ((370-head.width)//2, (400-head.height)//2))
    canvas.alpha_composite(backing, (199, 70))
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()

def find_video_url(obj):
    if isinstance(obj, dict):
        url = obj.get("url")
        if isinstance(url, str) and url.startswith(SPACE + "/"):
            return url
        for value in obj.values():
            result = find_video_url(value)
            if result:
                return result
    if isinstance(obj, list):
        for value in obj:
            result = find_video_url(value)
            if result:
                return result
    return None

def generate(image_bytes, filename, prompt):
    with requests.Session() as session:
        up = session.post(SPACE + "/gradio_api/upload",
                          files={"files": (filename, image_bytes, "image/png")},
                          timeout=90)
        up.raise_for_status()
        path = up.json()[0]
        image = {"path": path, "url": SPACE + "/gradio_api/file=" + path,
                 "orig_name": filename, "meta": {"_type": "gradio.FileData"}}
        data = [image, None, prompt, 6, "blurry, distorted anatomy, low quality",
                3.5, 1, 1, 42, True, 6, "UniPCMultistep", 3.0, 16, False, True]
        job = session.post(SPACE + "/gradio_api/call/generate_video",
                           json={"data": data}, timeout=90)
        job.raise_for_status()
        event_id = job.json().get("event_id")
        if not event_id:
            raise RuntimeError("Le service n'a pas retourné de tâche.")
        with session.get(SPACE + "/gradio_api/call/generate_video/" + event_id,
                         stream=True, timeout=(30, 240)) as response:
            response.raise_for_status()
            current = ""
            for raw in response.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if raw.startswith("event:"):
                    current = raw[6:].strip()
                elif raw.startswith("data:"):
                    if current == "error":
                        raise RuntimeError(raw[5:][:300])
                    if current == "complete":
                        video_url = find_video_url(json.loads(raw[5:]))
                        if not video_url:
                            raise RuntimeError("Le résultat ne contient pas de MP4 accessible.")
                        result = session.get(video_url, timeout=120)
                        result.raise_for_status()
                        return result.content
        raise RuntimeError("Le GPU gratuit n'a pas terminé la génération.")

def prepare_upload(upload):
    """Normalize common Android camera images to a small JPEG/PNG."""
    raw = upload.getvalue()
    if len(raw) > MAX_IMAGE:
        raise ValueError("Photo trop lourde (25 Mo maximum). Choisis une version plus petite.")
    try:
        with Image.open(io.BytesIO(raw)) as original:
            img = ImageOps.exif_transpose(original)
            img.thumbnail((MAX_PIXELS, MAX_PIXELS), Image.Resampling.LANCZOS)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, "white")
                background.paste(img, mask=img.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue()
    except Exception as exc:
        raise ValueError("Format non reconnu. Essaie une capture d’écran JPG ou PNG.") from exc


def run():
    st.subheader("🎬 Animation 2D — Wan 2.2")
    st.caption("Une image, un mouvement, une vidéo. Aucun découpage manuel.")
    st.info("Sur Android : sélectionne une photo dans Fichiers ou Galerie. L’aperçu confirme l’importation.")
    upload = st.file_uploader(
        "📷 Choisir une photo (JPG, PNG, WEBP, HEIC si pris en charge)",
        type=["png", "jpg", "jpeg", "webp", "heic", "heif"],
        key="wan_img_android_v3",
    )
    kind = st.radio("Que contient ton image ?", ["Personnage entier", "Tête seule"],
                    horizontal=True, key="wan_kind_v3")
    motion = st.text_area("Mouvement",
        "The cartoon character dances with natural arm and leg movements. "
        "Preserve the original face, clothing and 2D art style.", key="wan_motion_v3")
    prepared = None
    if upload is not None:
        try:
            normalized = prepare_upload(upload)
            st.success("✅ Photo reçue : " + upload.name)
            if kind == "Tête seule":
                st.warning("Corps cartoon expérimental : pas encore de génération IA fidèle du corps.")
                prepared = make_cartoon_body(normalized)
                st.image(prepared, caption="Personnage préparé", width=280)
                st.download_button("⬇️ Enregistrer le personnage", prepared,
                    "KarmaClip_personnage.png", "image/png", key="wan_character_dl_v3")
            else:
                prepared = normalized
                st.image(prepared, caption="Photo importée", width=280)
            st.caption("Image optimisée automatiquement pour limiter les échecs d’envoi.")
        except ValueError as exc:
            st.error(str(exc))
    if st.button("🎬 Générer la vidéo avec Wan 2.2", type="primary", key="wan_go_v3"):
        if not prepared:
            st.warning("Ajoute une image valide.")
        else:
            try:
                with st.spinner("Génération sur GPU partagé (disponibilité non garantie)…"):
                    st.session_state["wan_result_v3"] = generate(
                        prepared, "character.png", motion.strip())
                st.success("Vidéo générée.")
            except Exception as exc:
                st.error("Wan indisponible : " + str(exc))
    if st.session_state.get("wan_result_v3"):
        video = st.session_state["wan_result_v3"]
        st.video(video)
        st.download_button("⬇️ Télécharger le MP4", video,
            "KarmaClip_Wan22.mp4", "video/mp4", key="wan_video_dl_v3")
    st.link_button("Ouvrir NiftyVid (solution externe)",
                   "https://igorcsis.github.io/nifty-vid/")
    st.caption("Gratuit sous réserve de disponibilité de la démo publique.")
