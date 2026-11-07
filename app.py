
# -*- coding: utf-8 -*-
# KARMACLIP STUDIO
# IMAGE -> PROMPT -> VIDEO -> MONTAGE

import io
import json
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

STEPS = [
    "1. IMAGE",
    "2. PROMPT",
    "3. VIDÉO",
    "4. MONTAGE"
]

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
    "Photoréaliste",
    "Cinématographique",
    "Anime / manga",
    "Illustration",
    "Surréaliste",
    "Vintage",
    "Minimaliste",
    "Fantastique",
    "Noir et blanc"
]

FORMATS = {
    "Clip vertical 9:16": (1080, 1920),
    "Pochette carrée 1:1": (3000, 3000),
    "Paysage 16:9": (1920, 1080)
}

DEFAULTS = {
    "kc_step": STEPS[0],
    "kc_project": "Mon projet",
    "kc_image": None,
    "kc_description": "",
    "kc_lyrics": "",
    "kc_video_prompt": "",
    "kc_scenes": [],
    "kc_engine": "LoreMotion",
    "kc_final_video": None,
    "kc_title": "",
    "kc_artist": ""
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =====================================================
# NAVIGATION CORRIGEE
# =====================================================

def go_to(step):
    """Callback execute avant la creation des widgets."""
    st.session_state["kc_step"] = step


def navigation_button(label, destination, primary=False):
    st.button(
        label,
        on_click=go_to,
        args=(destination,),
        type="primary" if primary else "secondary",
        use_container_width=True
    )


# =====================================================
# FONCTIONS IMAGE
# =====================================================

def read_image(upload):
    if upload.size > 30 * 1024 * 1024:
        raise ValueError("Image trop volumineuse : maximum 30 Mo.")

    with Image.open(io.BytesIO(upload.getvalue())) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def png_bytes(image):
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer, format="PNG", optimize=True
    )
    return buffer.getvalue()


def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    return ImageFont.load_default()


def add_cover_text(image, title, artist):
    base = image.convert("RGBA")
    width, height = base.size

    overlay = Image.new(
        "RGBA", base.size, (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(overlay)
    draw.rectangle(
        (0, int(height * 0.72), width, height),
        fill=(0, 0, 0, 160)
    )

    base = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(base)

    if title.strip():
        draw.text(
            (width // 2, int(height * 0.81)),
            title.strip()[:45],
            font=get_font(max(20, width // 20)),
            anchor="mm",
            fill="white",
            stroke_width=2,
            stroke_fill="black"
        )

    if artist.strip():
        draw.text(
            (width // 2, int(height * 0.92)),
            artist.strip()[:45],
            font=get_font(max(16, width // 32)),
            anchor="mm",
            fill="white"
        )

    return base.convert("RGB")


def build_image_prompt(description, style, image_format,
                       lyrics="", details=""):
    parts = [
        "Create a beautiful, original image.",
        f"Style: {style}.",
        f"Format: {image_format}.",
        "Professional composition and lighting.",
        "Coherent anatomy, detailed textures.",
        "No watermark."
    ]

    if description.strip():
        parts.append("Subject: " + description.strip())

    if lyrics.strip():
        parts.append(
            "Visual inspiration from lyrics: "
            + lyrics.strip()[:600]
        )

    if details.strip():
        parts.append("Additional details: " + details.strip())

    return "\n".join(parts)


def build_video_prompt(scene, action, camera, mood,
                       duration, continuity):
    parts = [
        "Create a cinematic image-to-video sequence.",
        f"Duration: {duration} seconds.",
        f"Scene: {scene or 'Use reference image'}.",
        f"Action: {action}.",
        f"Camera: {camera}.",
        f"Mood: {mood}.",
        "Smooth natural movement.",
        "Stable perspective and anatomy."
    ]

    if continuity:
        parts.append(
            "Preserve faces, identities, clothing, "
            "colors and environment."
        )

    return "\n".join(parts)


def create_scenes(text, count):
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]

    if not lines:
        lines = ["Natural cinematic movement"]

    result = []

    for index in range(count):
        start = index * len(lines) // count
        end = (index + 1) * len(lines) // count

        description = " ".join(lines[start:end]).strip()

        if not description:
            description = lines[index % len(lines)]

        result.append({
            "number": index + 1,
            "duration": 5,
            "description": description
        })

    return result


# =====================================================
# MONTAGE VIDEO
# =====================================================

def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def run_ffmpeg(command, timeout=180):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr[-1500:] or "Erreur FFmpeg."
        )


def assemble_videos(clips, audio, size):
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg absent du serveur.")

    if not clips:
        raise ValueError("Aucune vidéo importée.")

    width, height = size

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        prepared = []

        for index, clip in enumerate(clips):
            source = root / f"source_{index}.mp4"
            target = root / f"scene_{index}.mp4"

            source.write_bytes(clip.getvalue())

            video_filter = (
                f"scale={width}:{height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,fps=25,format=yuv420p"
            )

            run_ffmpeg([
                "ffmpeg", "-y",
                "-i", str(source),
                "-vf", video_filter,
                "-an",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "26",
                str(target)
            ])

            prepared.append(target)

        manifest = root / "list.txt"

        manifest.write_text(
            "".join(
                f"file '{item.name}'\n"
                for item in prepared
            ),
            encoding="utf-8"
        )

        joined = root / "joined.mp4"

        run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(manifest),
            "-c", "copy",
            str(joined)
        ])

        if audio is None:
            return joined.read_bytes()

        suffix = Path(audio.name).suffix.lower() or ".mp3"
        music_path = root / ("music" + suffix)
        music_path.write_bytes(audio.getvalue())

        final_path = root / "final.mp4"

        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(joined),
            "-i", str(music_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(final_path)
        ])

        return final_path.read_bytes()


# =====================================================
# SAUVEGARDE
# =====================================================

def backup_project():
    fields = [
        "project", "description", "lyrics",
        "video_prompt", "scenes",
        "engine", "title", "artist"
    ]

    data = {
        field: st.session_state.get("kc_" + field)
        for field in fields
    }

    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "projet.json",
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )
        )

        if st.session_state.kc_image:
            archive.writestr(
                "image.png",
                st.session_state.kc_image
            )

    return buffer.getvalue()


def restore_project(upload):
    if upload.size > 80 * 1024 * 1024:
        raise ValueError("Archive trop volumineuse.")

    with zipfile.ZipFile(
        io.BytesIO(upload.getvalue())
    ) as archive:
        data = json.loads(
            archive.read("projet.json")
        )

        fields = [
            "project", "description", "lyrics",
            "video_prompt", "scenes",
            "engine", "title", "artist"
        ]

        for field in fields:
            if field in data:
                st.session_state[
                    "kc_" + field
                ] = data[field]

        if "image.png" in archive.namelist():
            raw = archive.read("image.png")

            with Image.open(io.BytesIO(raw)) as img:
                img.verify()

            st.session_state.kc_image = raw


# =====================================================
# INTERFACE
# =====================================================

st.title("🎬 KarmaClip Studio")
st.caption("IMAGE → PROMPT facultatif → VIDÉO → MONTAGE")

st.text_input(
    "Nom du projet",
    key="kc_project"
)

st.radio(
    "Étape du projet",
    STEPS,
    horizontal=True,
    key="kc_step"
)

st.divider()


# =====================================================
# 1. IMAGE
# =====================================================

if st.session_state.kc_step == STEPS[0]:

    st.header("🎨 Studio Image")

    mode = st.radio(
        "Que veux-tu faire ?",
        [
            "Créer une image",
            "Modifier une photo",
            "Créer une pochette"
        ]
    )

    st.text_area(
        "Décris ton image",
        key="kc_description",
        height=130,
        placeholder="Un tigre au regard intense..."
    )

    style = st.selectbox("Style visuel", STYLES)
    image_format = st.selectbox(
        "Format",
        list(FORMATS)
    )

    st.text_area(
        "Paroles (facultatives)",
        key="kc_lyrics",
        height=120
    )

    audio_reference = st.file_uploader(
        "Musique (facultative)",
        type=["mp3", "wav", "m4a"],
        key="kc_audio_reference"
    )

    if audio_reference:
        st.audio(audio_reference)

    details = st.text_area(
        "Précisions supplémentaires",
        placeholder="Décor, lumière, vêtements, pose..."
    )

    prompt = build_image_prompt(
        st.session_state.kc_description,
        style,
        image_format,
        st.session_state.kc_lyrics,
        details
    )

    st.subheader("Prompt image")
    st.code(prompt, language=None)

    st.info(
        "La génération d'une nouvelle image IA "
        "passe encore par un site externe."
    )

    image_engine = st.selectbox(
        "Générateur d'images",
        list(IMAGE_SITES)
    )

    st.link_button(
        "🎨 Ouvrir le générateur",
        IMAGE_SITES[image_engine],
        use_container_width=True
    )

    st.divider()
    st.subheader("Importer et retoucher")

    upload = st.file_uploader(
        "Photo ou image générée",
        type=["png", "jpg", "jpeg", "webp"],
        key="kc_image_upload"
    )

    if upload:
        try:
            original = read_image(upload)
            st.image(original, caption="Image originale")

            col1, col2 = st.columns(2)

            with col1:
                brightness = st.slider(
                    "Luminosité", 0.2, 2.0, 1.0, 0.1
                )
                contrast = st.slider(
                    "Contraste", 0.2, 2.0, 1.0, 0.1
                )
                saturation = st.slider(
                    "Couleurs", 0.0, 2.0, 1.0, 0.1
                )

            with col2:
                sharpness = st.slider(
                    "Netteté", 0.0, 3.0, 1.0, 0.1
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
                FORMATS[image_format],
                method=Image.Resampling.LANCZOS
            )

            if mode == "Créer une pochette":
                st.text_input(
                    "Titre du single",
                    key="kc_title"
                )
                st.text_input(
                    "Artiste",
                    key="kc_artist"
                )

                if st.checkbox(
                    "Afficher le titre",
                    value=True
                ):
                    result = add_cover_text(
                        result,
                        st.session_state.kc_title,
                        st.session_state.kc_artist
                    )

            result_data = png_bytes(result)

            st.subheader("Résultat")
            st.image(result_data)

            st.download_button(
                "💾 Enregistrer l'image",
                result_data,
                file_name="KarmaClip_image.png",
                mime="image/png",
                use_container_width=True
            )

            if st.button(
                "✅ Valider cette image",
                type="primary",
                use_container_width=True
            ):
                st.session_state.kc_image = result_data
                st.success("Image conservée dans le projet.")

        except Exception as exc:
            st.error(f"Erreur image : {exc}")

    if st.session_state.kc_image:
        st.success("Image du projet prête.")
        st.image(
            st.session_state.kc_image,
            width=260
        )

    col1, col2 = st.columns(2)

    with col1:
        navigation_button(
            "➡️ Préparer un prompt",
            STEPS[1]
        )

    with col2:
        navigation_button(
            "⏭️ Passer à la vidéo",
            STEPS[2],
            primary=True
        )


# =====================================================
# 2. PROMPT
# =====================================================

elif st.session_state.kc_step == STEPS[1]:

    st.header("✍️ Prompt vidéo")
    st.info("Cette étape est facultative.")

    if st.session_state.kc_image:
        st.image(
            st.session_state.kc_image,
            width=240
        )

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
            "Fixe",
            "Travelling avant",
            "Travelling arrière",
            "Panoramique",
            "Rotation",
            "Caméra à l'épaule"
        ]
    )

    mood = st.selectbox(
        "Ambiance",
        [
            "Cinématographique",
            "Festive",
            "Dynamique",
            "Mélancolique",
            "Mystérieuse",
            "Épique",
            "Naturelle"
        ]
    )

    duration = st.selectbox(
        "Durée de la scène",
        [3, 4, 5, 6, 8, 10],
        index=2
    )

    continuity = st.checkbox(
        "Conserver les visages et vêtements",
        value=True
    )

    generated = build_video_prompt(
        scene,
        action or "Natural movement",
        camera,
        mood,
        duration,
        continuity
    )

    edited_prompt = st.text_area(
        "Prompt vidéo modifiable",
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
    st.subheader("Storyboard")

    story = st.text_area(
        "Paroles ou scénario",
        value=st.session_state.kc_lyrics,
        height=160
    )

    count = st.number_input(
        "Nombre de scènes de 5 secondes",
        min_value=1,
        max_value=100,
        value=6
    )

    if st.button("Créer les scènes"):
        st.session_state.kc_scenes = create_scenes(
            story or scene,
            count
        )

    for index, item in enumerate(
        st.session_state.kc_scenes
    ):
        with st.expander(f"Scène {index + 1}"):
            description = st.text_area(
                "Description",
                value=item["description"],
                key=f"kc_scene_{index}"
            )

            st.session_state.kc_scenes[
                index
            ]["description"] = description

            st.code(
                build_video_prompt(
                    description,
                    action or "Natural movement",
                    camera,
                    mood,
                    5,
                    continuity
                ),
                language=None
            )

    # La sauvegarde du prompt s'effectue
    # dans le callback, avant le prochain rerun.
    def save_prompt_and_continue():
        st.session_state.kc_video_prompt = (
            st.session_state.kc_prompt_to_save
        )
        st.session_state.kc_step = STEPS[2]

    st.session_state.kc_prompt_to_save = edited_prompt

    st.button(
        "➡️ Passer à la vidéo",
        on_click=save_prompt_and_continue,
        type="primary",
        use_container_width=True
    )


# =====================================================
# 3. VIDEO
# =====================================================

elif st.session_state.kc_step == STEPS[2]:

    st.header("🎥 Génération vidéo")
    st.success("Mode manuel activé.")

    if st.session_state.kc_image:
        st.image(
            st.session_state.kc_image,
            width=260
        )

        st.download_button(
            "💾 Télécharger l'image de référence",
            st.session_state.kc_image,
            file_name="KarmaClip_reference.png",
            mime="image/png",
            use_container_width=True
        )

    engine = st.selectbox(
        "Choisir le moteur",
        list(VIDEO_SITES),
        index=(
            list(VIDEO_SITES).index(
                st.session_state.kc_engine
            )
            if st.session_state.kc_engine in VIDEO_SITES
            else 0
        )
    )

    st.session_state.kc_engine = engine

    st.link_button(
        f"🚀 Ouvrir {engine}",
        VIDEO_SITES[engine],
        use_container_width=True
    )

    current_prompt = (
        st.session_state.kc_video_prompt
        or build_video_prompt(
            st.session_state.kc_description,
            "Natural movement",
            "Fixed camera",
            "Cinematic",
            5,
            True
        )
    )

    prompt = st.text_area(
        "Prompt à utiliser",
        value=current_prompt,
        height=200
    )

    st.code(prompt, language=None)

    st.caption(
        "Copie le prompt et utilise l'image "
        "sur le site du générateur choisi."
    )

    st.subheader("Tous les moteurs")

    for name, url in VIDEO_SITES.items():
        with st.expander(name):
            st.link_button(
                f"Ouvrir {name}",
                url,
                use_container_width=True
            )

    st.divider()
    st.subheader("Mode automatique")

    st.toggle(
        "Automatique",
        value=False,
        disabled=True,
        help="Pas encore connecté."
    )

    st.info(
        "Le mode automatique sera ajouté "
        "après intégration d'un moteur fonctionnel."
    )

    navigation_button(
        "➡️ Passer au montage",
        STEPS[3],
        primary=True
    )


# =====================================================
# 4. MONTAGE
# =====================================================

elif st.session_state.kc_step == STEPS[3]:

    st.header("🎞️ Montage vidéo")

    clips = st.file_uploader(
        "Importer les vidéos MP4",
        type=["mp4"],
        accept_multiple_files=True,
        key="kc_clips"
    )

    if clips:
        for index, clip in enumerate(clips):
            with st.expander(
                f"{index + 1}. {clip.name}"
            ):
                st.video(clip)

    audio = st.file_uploader(
        "Musique facultative",
        type=["mp3", "wav", "m4a"],
        key="kc_music"
    )

    if audio:
        st.audio(audio)

    output_format = st.selectbox(
        "Format du montage",
        [
            "Vertical 9:16",
            "Carré 1:1",
            "Paysage 16:9"
        ]
    )

    sizes = {
        "Vertical 9:16": (720, 1280),
        "Carré 1:1": (1080, 1080),
        "Paysage 16:9": (1280, 720)
    }

    if not ffmpeg_available():
        st.warning(
            "FFmpeg absent du serveur. "
            "Le montage ne peut pas fonctionner ici."
        )

    if st.button(
        "🎬 Assembler les vidéos",
        type="primary",
        disabled=not clips or not ffmpeg_available(),
        use_container_width=True
    ):
        try:
            with st.spinner("Montage en cours..."):
                result = assemble_videos(
                    clips,
                    audio,
                    sizes[output_format]
                )

            st.session_state.kc_final_video = result
            st.success("Montage terminé.")

        except Exception as exc:
            st.error(f"Montage impossible : {exc}")

    if st.session_state.kc_final_video:
        st.video(st.session_state.kc_final_video)

        st.download_button(
            "⬇️ Télécharger le MP4 final",
            st.session_state.kc_final_video,
            file_name="KarmaClip_final.mp4",
            mime="video/mp4",
            use_container_width=True
        )


# =====================================================
# SAUVEGARDE ET RESTAURATION
# =====================================================

st.divider()

with st.expander("💾 Sauvegarde du projet"):

    st.download_button(
        "Sauvegarder le projet ZIP",
        backup_project(),
        file_name="KarmaClip_projet.zip",
        mime="application/zip",
        use_container_width=True
    )

    restore = st.file_uploader(
        "Restaurer un projet ZIP",
        type=["zip"],
        key="kc_restore"
    )

    if restore and st.button("Restaurer"):
        try:
            restore_project(restore)
            st.success("Projet restauré.")
            st.rerun()
        except Exception as exc:
            st.error(f"Restauration impossible : {exc}")


with st.expander("⚙️ Nouveau projet"):

    def reset_project():
        for key in list(st.session_state):
            if key.startswith("kc_"):
                del st.session_state[key]

    st.button(
        "🧹 Effacer le projet actuel",
        on_click=reset_project,
        use_container_width=True
    )

st.caption(
    "KarmaClip Studio | Image → Prompt → Vidéo → Montage"
)
