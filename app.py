
# -*- coding: utf-8 -*-
# KARMACLIP STUDIO - APP.PY COMPLET
# IMAGE -> PROMPT (FACULTATIF) -> VIDEO -> MONTAGE
# Dependances : streamlit, Pillow
# Montage MP4 : FFmpeg installe sur le serveur

import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, ImageEnhance, ImageDraw, ImageFont

st.set_page_config(
    page_title="KarmaClip Studio",
    page_icon="🎬",
    layout="wide"
)

st.markdown("""
<style>
.block-container {max-width:1100px;padding-top:1rem}
.stButton button,.stDownloadButton button {
    min-height:46px;border-radius:12px
}
</style>
""", unsafe_allow_html=True)

VIDEO_SITES = {
    "WAN 2.2": "https://wan.video/",
    "LoreMotion": "https://loremotion.com/",
    "LTX Studio": "https://ltx.studio/",
    "Kling AI": "https://klingai.com/",
    "Google Veo / Flow": "https://labs.google/fx/tools/flow",
    "Vidu": "https://www.vidu.com/"
}

IMAGE_SITES = {
    "Bing Image Creator": "https://www.bing.com/images/create",
    "Leonardo AI": "https://app.leonardo.ai/",
    "Adobe Firefly": "https://firefly.adobe.com/"
}

STYLES = [
    "Photoréaliste", "Cinématographique",
    "Anime / manga", "Illustration",
    "Surréaliste", "Vintage", "Minimaliste",
    "Fantastique", "Noir et blanc"
]

SIZES = {
    "Clip vertical 9:16": (1080, 1920),
    "Pochette 1:1": (3000, 3000),
    "Paysage 16:9": (1920, 1080)
}

DEFAULTS = {
    "step": "1. IMAGE",
    "project": "Mon projet",
    "image": None,
    "description": "",
    "lyrics": "",
    "video_prompt": "",
    "scenes": [],
    "engine": "LoreMotion",
    "final_video": None,
    "title": "",
    "artist": ""
}

for name, value in DEFAULTS.items():
    key = "kc_" + name
    if key not in st.session_state:
        st.session_state[key] = value


# ==================================================
# FONCTIONS IMAGE
# ==================================================

def read_image(upload):
    if upload.size > 30 * 1024 * 1024:
        raise ValueError("Image supérieure à 30 Mo.")

    with Image.open(io.BytesIO(upload.getvalue())) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def to_png(im):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def cover_text(im, title, artist):
    im = im.convert("RGBA")
    w, h = im.size

    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle(
        (0, int(h * .72), w, h),
        fill=(0, 0, 0, 160)
    )
    im = Image.alpha_composite(im, layer)
    draw = ImageDraw.Draw(im)

    if title.strip():
        draw.text(
            (w // 2, int(h * .81)),
            title.strip()[:45],
            font=font(max(20, w // 20)),
            anchor="mm",
            fill="white",
            stroke_width=2,
            stroke_fill="black"
        )

    if artist.strip():
        draw.text(
            (w // 2, int(h * .92)),
            artist.strip()[:45],
            font=font(max(16, w // 32)),
            anchor="mm",
            fill="white"
        )

    return im.convert("RGB")


def image_prompt(description, style, ratio, lyrics, details):
    lines = [
        "Create a beautiful original image.",
        "Style: " + style,
        "Composition: " + ratio,
        "High quality, coherent anatomy, professional lighting.",
        "No watermark."
    ]
    if description.strip():
        lines.append("Subject: " + description.strip())
    if lyrics.strip():
        lines.append(
            "Visual inspiration from lyrics: "
            + lyrics.strip()[:600]
        )
    if details.strip():
        lines.append("Additional details: " + details.strip())
    return "\n".join(lines)


def video_prompt(scene, action, camera, mood, seconds, locked):
    lines = [
        "Create a cinematic image-to-video shot.",
        "Duration: " + str(seconds) + " seconds.",
        "Scene: " + (scene.strip() or "Reference image"),
        "Action: " + action,
        "Camera: " + camera,
        "Mood: " + mood,
        "Natural movement, smooth animation.",
        "Consistent perspective and anatomy."
    ]
    if locked:
        lines.append(
            "Preserve face, identity, clothing, "
            "colors and background."
        )
    return "\n".join(lines)


def make_scenes(text, count):
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    if not lines:
        lines = ["Natural cinematic movement"]

    result = []
    for i in range(count):
        a = i * len(lines) // count
        b = (i + 1) * len(lines) // count
        content = " ".join(lines[a:b]).strip()
        if not content:
            content = lines[i % len(lines)]
        result.append({
            "number": i + 1,
            "duration": 5,
            "description": content
        })
    return result


# ==================================================
# SAUVEGARDE
# ==================================================

def backup_project():
    data = {
        name: st.session_state.get("kc_" + name)
        for name in [
            "project", "description", "lyrics",
            "video_prompt", "scenes",
            "engine", "title", "artist"
        ]
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "projet.json",
            json.dumps(data, ensure_ascii=False, indent=2)
        )
        if st.session_state.kc_image:
            z.writestr("image.png", st.session_state.kc_image)
    return buf.getvalue()


def restore_project(upload):
    if upload.size > 80 * 1024 * 1024:
        raise ValueError("Archive trop volumineuse.")

    with zipfile.ZipFile(io.BytesIO(upload.getvalue())) as z:
        data = json.loads(z.read("projet.json"))
        allowed = [
            "project", "description", "lyrics",
            "video_prompt", "scenes",
            "engine", "title", "artist"
        ]
        for name in allowed:
            if name in data:
                st.session_state["kc_" + name] = data[name]

        if "image.png" in z.namelist():
            raw = z.read("image.png")
            with Image.open(io.BytesIO(raw)) as im:
                im.verify()
            st.session_state.kc_image = raw


# ==================================================
# MONTAGE FFMPEG
# ==================================================

def ffmpeg_ok():
    return shutil.which("ffmpeg") is not None


def ffmpeg_run(args, timeout=180):
    p = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-1200:])


def montage(clips, audio, size):
    if not ffmpeg_ok():
        raise RuntimeError("FFmpeg indisponible.")
    if not clips:
        raise ValueError("Aucun MP4 importé.")

    w, h = size

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        prepared = []

        for i, clip in enumerate(clips):
            src = root / f"input_{i}.mp4"
            dst = root / f"clip_{i}.mp4"
            src.write_bytes(clip.getvalue())

            vf = (
                f"scale={w}:{h}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,fps=25,format=yuv420p"
            )

            ffmpeg_run([
                "ffmpeg", "-y", "-i", str(src),
                "-vf", vf, "-an",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "26",
                str(dst)
            ])
            prepared.append(dst)

        manifest = root / "list.txt"
        manifest.write_text(
            "".join(f"file '{p.name}'\n" for p in prepared),
            encoding="utf-8"
        )

        joined = root / "joined.mp4"
        ffmpeg_run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(manifest),
            "-c", "copy",
            str(joined)
        ])

        if audio is None:
            return joined.read_bytes()

        suffix = Path(audio.name).suffix.lower() or ".mp3"
        music = root / ("music" + suffix)
        music.write_bytes(audio.getvalue())

        output = root / "final.mp4"
        ffmpeg_run([
            "ffmpeg", "-y",
            "-i", str(joined),
            "-i", str(music),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(output)
        ])
        return output.read_bytes()


# ==================================================
# INTERFACE GENERALE
# ==================================================

st.title("🎬 KarmaClip Studio")
st.caption("IMAGE → PROMPT facultatif → VIDÉO → MONTAGE")

st.text_input("Nom du projet", key="kc_project")

st.radio(
    "Étape du projet",
    ["1. IMAGE", "2. PROMPT", "3. VIDÉO", "4. MONTAGE"],
    horizontal=True,
    key="kc_step"
)

st.divider()


# ==================================================
# 1. IMAGE
# ==================================================

if st.session_state.kc_step == "1. IMAGE":

    st.header("🎨 Studio image")

    mode = st.radio(
        "Que veux-tu faire ?",
        [
            "Créer une image",
            "Modifier une photo",
            "Créer une pochette"
        ]
    )

    st.text_area(
        "Décris l'image souhaitée",
        key="kc_description",
        height=130,
        placeholder="Un tigre au regard intense..."
    )

    style = st.selectbox("Style", STYLES)
    ratio = st.selectbox("Format", list(SIZES))

    st.text_area(
        "Paroles (facultatives)",
        key="kc_lyrics",
        height=120
    )

    audio_image = st.file_uploader(
        "Musique facultative",
        type=["mp3", "wav", "m4a"],
        key="kc_audio_image"
    )
    if audio_image:
        st.audio(audio_image)

    details = st.text_area(
        "Précisions supplémentaires",
        placeholder="Décor, pose, couleurs, lumière..."
    )

    prompt = image_prompt(
        st.session_state.kc_description,
        style,
        ratio,
        st.session_state.kc_lyrics,
        details
    )

    st.subheader("Prompt image")
    st.code(prompt, language=None)

    st.info(
        "La génération IA d'une image nouvelle "
        "passe actuellement par un site externe."
    )

    provider = st.selectbox(
        "Générateur d'images",
        list(IMAGE_SITES)
    )
    st.link_button(
        "🎨 Ouvrir le générateur",
        IMAGE_SITES[provider],
        use_container_width=True
    )

    st.divider()
    st.subheader("Importer et retoucher")

    upload = st.file_uploader(
        "Photo ou image générée",
        type=["png", "jpg", "jpeg", "webp"],
        key="kc_upload_image"
    )

    if upload:
        try:
            original = read_image(upload)

            st.image(original, caption="Original")

            c1, c2 = st.columns(2)

            with c1:
                brightness = st.slider(
                    "Luminosité", .2, 2.0, 1.0, .1
                )
                contrast = st.slider(
                    "Contraste", .2, 2.0, 1.0, .1
                )
                saturation = st.slider(
                    "Couleurs", 0.0, 2.0, 1.0, .1
                )

            with c2:
                sharpness = st.slider(
                    "Netteté", 0.0, 3.0, 1.0, .1
                )
                rotation = st.selectbox(
                    "Rotation", [0, 90, 180, 270]
                )
                grayscale = st.checkbox("Noir et blanc")

            result = original.rotate(
                rotation, expand=True
            )
            result = ImageEnhance.Brightness(
                result
            ).enhance(brightness)
            result = ImageEnhance.Contrast(
                result
            ).enhance(contrast)
            result = ImageEnhance.Color(
                result
            ).enhance(saturation)
            result = ImageEnhance.Sharpness(
                result
            ).enhance(sharpness)

            if grayscale:
                result = result.convert("L").convert("RGB")

            result = ImageOps.fit(
                result,
                SIZES[ratio],
                method=Image.Resampling.LANCZOS
            )

            if mode == "Créer une pochette":
                st.text_input(
                    "Titre du single", key="kc_title"
                )
                st.text_input(
                    "Artiste", key="kc_artist"
                )
                if st.checkbox(
                    "Ajouter le titre sur l'image",
                    value=True
                ):
                    result = cover_text(
                        result,
                        st.session_state.kc_title,
                        st.session_state.kc_artist
                    )

            result_bytes = to_png(result)

            st.subheader("Résultat")
            st.image(result_bytes)

            st.download_button(
                "💾 Enregistrer l'image",
                result_bytes,
                file_name="KarmaClip_image.png",
                mime="image/png",
                use_container_width=True
            )

            if st.button(
                "✅ Valider cette image",
                type="primary",
                use_container_width=True
            ):
                st.session_state.kc_image = result_bytes
                st.success("Image conservée dans le projet.")

        except Exception as exc:
            st.error(str(exc))

    if st.session_state.kc_image:
        st.success("Image du projet prête.")
        st.image(st.session_state.kc_image, width=260)

    c1, c2 = st.columns(2)

    with c1:
        if st.button(
            "➡️ Préparer le prompt",
            use_container_width=True
        ):
            st.session_state.kc_step = "2. PROMPT"
            st.rerun()

    with c2:
        if st.button(
            "⏭️ Vidéo sans prompt",
            use_container_width=True
        ):
            st.session_state.kc_step = "3. VIDÉO"
            st.rerun()


# ==================================================
# 2. PROMPT VIDEO
# ==================================================

elif st.session_state.kc_step == "2. PROMPT":

    st.header("✍️ Prompt vidéo")
    st.caption("Étape facultative.")

    if st.session_state.kc_image:
        st.image(st.session_state.kc_image, width=240)

    scene = st.text_area(
        "Que doit-il se passer ?",
        value=st.session_state.kc_description,
        height=130
    )

    action = st.text_area(
        "Mouvements",
        placeholder="Le personnage marche puis sourit..."
    )

    camera = st.selectbox(
        "Caméra",
        [
            "Fixe", "Travelling avant",
            "Travelling arrière", "Panoramique",
            "Rotation", "Caméra à l'épaule"
        ]
    )

    mood = st.selectbox(
        "Ambiance",
        [
            "Cinématographique", "Festive",
            "Dynamique", "Mélancolique",
            "Mystérieuse", "Épique", "Naturelle"
        ]
    )

    seconds = st.selectbox(
        "Durée de la scène",
        [3, 4, 5, 6, 8, 10],
        index=2
    )

    locked = st.checkbox(
        "Conserver les visages et les vêtements",
        value=True
    )

    generated = video_prompt(
        scene,
        action or "Natural movement",
        camera,
        mood,
        seconds,
        locked
    )

    edited_prompt = st.text_area(
        "Prompt final modifiable",
        value=generated,
        height=220
    )

    st.code(edited_prompt, language=None)

    if st.button(
        "💾 Conserver ce prompt",
        use_container_width=True
    ):
        st.session_state.kc_video_prompt = edited_prompt
        st.success("Prompt conservé.")

    st.divider()
    st.subheader("Storyboard automatique")

    story = st.text_area(
        "Paroles ou scénario",
        value=st.session_state.kc_lyrics,
        height=160
    )

    count = st.number_input(
        "Nombre de scènes de 5 secondes",
        1, 100, 6
    )

    if st.button("Créer les scènes"):
        st.session_state.kc_scenes = make_scenes(
            story or scene, count
        )

    for i, item in enumerate(st.session_state.kc_scenes):
        with st.expander(f"Scène {i + 1}"):
            new_text = st.text_area(
                "Description",
                value=item["description"],
                key=f"kc_scene_{i}"
            )
            st.session_state.kc_scenes[i][
                "description"
            ] = new_text

            st.code(
                video_prompt(
                    new_text,
                    action or "Natural movement",
                    camera, mood, 5, locked
                ),
                language=None
            )

    if st.button(
        "➡️ Passer à la vidéo",
        type="primary",
        use_container_width=True
    ):
        st.session_state.kc_video_prompt = edited_prompt
        st.session_state.kc_step = "3. VIDÉO"
        st.rerun()


# ==================================================
# 3. VIDEO MANUELLE
# ==================================================

elif st.session_state.kc_step == "3. VIDÉO":

    st.header("🎥 Génération vidéo")

    st.success("Mode manuel activé.")

    if st.session_state.kc_image:
        st.image(st.session_state.kc_image, width=260)
        st.download_button(
            "💾 Télécharger l'image de référence",
            st.session_state.kc_image,
            "KarmaClip_reference.png",
            mime="image/png",
            use_container_width=True
        )

    engine = st.selectbox(
        "Choisir le moteur",
        list(VIDEO_SITES),
        index=list(VIDEO_SITES).index(
            st.session_state.kc_engine
        ) if st.session_state.kc_engine in VIDEO_SITES else 0
    )

    st.session_state.kc_engine = engine

    st.link_button(
        f"🚀 Ouvrir {engine}",
        VIDEO_SITES[engine],
        use_container_width=True
    )

    prompt = st.text_area(
        "Prompt à utiliser",
        value=st.session_state.kc_video_prompt
        or video_prompt(
            st.session_state.kc_description,
            "Natural movement",
            "Fixed camera",
            "Cinematic",
            5,
            True
        ),
        height=200
    )

    st.code(prompt, language=None)

    st.caption(
        "Copie le prompt, ouvre le site choisi, "
        "ajoute ton image et génère le MP4."
    )

    st.subheader("Autres moteurs")

    for name, url in VIDEO_SITES.items():
        with st.expander(name):
            st.link_button(
                "Ouvrir " + name,
                url,
                use_container_width=True
            )

    st.divider()
    st.subheader("Mode automatique")

    st.toggle(
        "Automatique",
        value=False,
        disabled=True,
        help="Non connecté pour le moment."
    )

    st.info(
        "L'automatique sera activé uniquement "
        "après connexion et test réel d'un moteur."
    )

    if st.button(
        "➡️ Passer au montage",
        type="primary",
        use_container_width=True
    ):
        st.session_state.kc_step = "4. MONTAGE"
        st.rerun()


# ==================================================
# 4. MONTAGE
# ==================================================

elif st.session_state.kc_step == "4. MONTAGE":

    st.header("🎞️ Montage vidéo")

    clips = st.file_uploader(
        "Importer les MP4",
        type=["mp4"],
        accept_multiple_files=True,
        key="kc_clips"
    )

    if clips:
        for i, clip in enumerate(clips):
            with st.expander(
                f"{i + 1}. {clip.name}"
            ):
                st.video(clip)

    audio = st.file_uploader(
        "Musique facultative",
        type=["mp3", "wav", "m4a"],
        key="kc_music"
    )

    if audio:
        st.audio(audio)

    ratio = st.selectbox(
        "Format du montage",
        ["Vertical 9:16", "Carré 1:1", "Paysage 16:9"]
    )

    sizes = {
        "Vertical 9:16": (720, 1280),
        "Carré 1:1": (1080, 1080),
        "Paysage 16:9": (1280, 720)
    }

    if not ffmpeg_ok():
        st.warning(
            "FFmpeg est absent du serveur. "
            "Le montage ne peut pas fonctionner ici."
        )

    if st.button(
        "🎬 Assembler les MP4",
        type="primary",
        disabled=not clips or not ffmpeg_ok(),
        use_container_width=True
    ):
        try:
            with st.spinner("Montage en cours..."):
                st.session_state.kc_final_video = montage(
                    clips, audio, sizes[ratio]
                )
            st.success("Montage terminé.")
        except Exception as exc:
            st.error(f"Montage impossible : {exc}")

    if st.session_state.kc_final_video:
        st.video(st.session_state.kc_final_video)
        st.download_button(
            "⬇️ Télécharger le MP4 final",
            st.session_state.kc_final_video,
            "KarmaClip_final.mp4",
            mime="video/mp4",
            use_container_width=True
        )


# ==================================================
# SAUVEGARDE ET OPTIONS
# ==================================================

st.divider()

with st.expander("💾 Sauvegarder / restaurer le projet"):

    st.download_button(
        "Sauvegarder le projet ZIP",
        backup_project(),
        "KarmaClip_projet.zip",
        mime="application/zip",
        use_container_width=True
    )

    restore = st.file_uploader(
        "Importer un projet ZIP",
        type=["zip"],
        key="kc_restore"
    )

    if restore and st.button("Restaurer"):
        try:
            restore_project(restore)
            st.success("Projet restauré.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with st.expander("⚙️ Nouveau projet"):

    if st.button("🧹 Effacer le projet actuel"):
        for key in list(st.session_state):
            if key.startswith("kc_"):
                del st.session_state[key]
        st.rerun()

st.caption(
    "KarmaClip Studio | Image → Prompt → Vidéo → Montage"
)
