
import io
import json
import zipfile
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

st.set_page_config(
    page_title="KarmaClip Studio",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

STEPS = [
    "🎨 Image",
    "✍️ Prompt",
    "🎥 Vidéo",
    "🎞️ Montage",
]

ENGINES = {
    "LoreMotion": "https://loremotion.com/generate/",
    "WAN": "https://wan2.video/fr/free-ai-video-generator",
    "NiftyVid": "https://igorcsis.github.io/nifty-vid/",
}

SIZES = {
    "Clip vertical 9:16": (1080, 1920),
    "Pochette carrée 1:1": (3000, 3000),
    "Paysage 16:9": (1920, 1080),
}

DEFAULT = {
    "step": STEPS[0],
    "project": "Mon clip",
    "idea": "",
    "lyrics": "",
    "style": "Cinématographique",
    "format": "Clip vertical 9:16",
    "image": None,
    "image_prompt": "",
    "video_prompt": "",
    "movement": "Mouvement naturel et fluide",
    "camera": "Travelling lent",
    "mood": "Cinématographique",
    "duration": 5,
    "continuity": True,
    "scenes": [],
    "engine": "LoreMotion",
    "final": None,
    "title": "",
    "artist": "",
    "image_version": 0,
}

for k, v in DEFAULT.items():
    if "kc_" + k not in st.session_state:
        st.session_state["kc_" + k] = v

st.markdown(
    """
<style>
.block-container {
    max-width: 790px;
    padding-top: 1rem;
    padding-bottom: 4rem;
}
div.stButton button,
div.stDownloadButton button,
div.stLinkButton a {
    min-height: 49px;
    border-radius: 13px;
    font-weight: 650;
}
div[data-testid="stImage"] img {
    border-radius: 15px;
}
h1, h2 {
    letter-spacing: -.025em;
}
.kc-sub {
    opacity: .7;
    margin-top: -.6rem;
    margin-bottom: 1.3rem;
}
</style>
""",
    unsafe_allow_html=True,
)


def go(step):
    st.session_state.kc_step = step


def nav(label, step, primary=True):
    st.button(
        label,
        on_click=go,
        args=(step,),
        type="primary" if primary else "secondary",
        use_container_width=True,
    )


def png(im):
    out = io.BytesIO()
    im.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def load(raw):
    with Image.open(io.BytesIO(raw)) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def image_prompt():
    s = st.session_state
    parts = [
        f"Create an original {s.kc_style.lower()} image, "
        f"{s.kc_format}.",
    ]

    if s.kc_idea.strip():
        parts.append(
            f"Subject and story: {s.kc_idea.strip()}."
        )

    if s.kc_lyrics.strip():
        parts.append(
            "Inspired by these lyrics: "
            + s.kc_lyrics[:700]
        )

    parts.append(
        "Professional composition, coherent details, "
        "natural anatomy, no watermarks."
    )
    return "\n".join(parts)


def video_prompt(scene=None):
    s = st.session_state

    subject = (
        scene if scene is not None else s.kc_idea
    ).strip()

    if not subject:
        subject = "Animate the supplied reference image"

    parts = [
        f"Scene: {subject}.",
        f"Movement: {s.kc_movement}.",
        f"Camera: {s.kc_camera}.",
        f"Mood: {s.kc_mood}.",
        f"Duration: {s.kc_duration} seconds.",
    ]

    if s.kc_continuity:
        parts.append(
            "Preserve subject identity, face, clothes "
            "and environment between shots."
        )
    else:
        parts.append(
            "Allow visual changes between shots."
        )

    parts.append(
        "Smooth cinematic motion, stable anatomy, "
        "no watermark."
    )

    return "\n".join(parts)


def build_scenes(text, n):
    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip() and not x.strip().startswith("[")
    ]

    if not lines:
        lines = [
            st.session_state.kc_idea
            or "Cinematic movement"
        ]

    result = []

    for i in range(n):
        start = i * len(lines) // n
        end = (i + 1) * len(lines) // n

        description = " ".join(
            lines[start:end]
        ).strip()

        if not description:
            description = lines[i % len(lines)]

        result.append({
            "description": description,
            "duration": 5,
        })

    return result


def reset():
    for k in list(st.session_state):
        if k.startswith("kc_"):
            del st.session_state[k]


def export_project():
    data = {
        k: st.session_state.get("kc_" + k)
        for k in DEFAULT
        if k not in ("image", "final")
    }

    buf = io.BytesIO()

    with zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as z:
        z.writestr(
            "project.json",
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
        )

        if st.session_state.kc_image:
            z.writestr(
                "image.png",
                st.session_state.kc_image,
            )

    return buf.getvalue()


def import_project(raw):
    with zipfile.ZipFile(
        io.BytesIO(raw)
    ) as z:
        if "project.json" not in z.namelist():
            raise ValueError(
                "Fichier project.json manquant"
            )

        data = json.loads(
            z.read("project.json")
        )

        for k in DEFAULT:
            if (
                k in data
                and k not in ("image", "final")
                and isinstance(data[k], type(DEFAULT[k]))
            ):
                st.session_state["kc_" + k] = data[k]

        if "image.png" in z.namelist():
            raw_image = z.read("image.png")
            st.session_state.kc_image = png(
                load(raw_image)
            )

        st.session_state.kc_final = None
        st.session_state.kc_image_version += 1


def montage(files, music, size):
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg non installé sur le serveur"
        )

    def run(cmd):
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240,
        )

        if p.returncode:
            raise RuntimeError(p.stderr[-900:])

    w, h = size

    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        paths = []

        for i, f in enumerate(files):
            src = folder / f"input_{i}.mp4"
            dst = folder / f"clip_{i}.mp4"

            src.write_bytes(f.getvalue())

            vf = (
                f"scale={w}:{h}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,fps=25,format=yuv420p"
            )

            run([
                "ffmpeg", "-y",
                "-i", str(src),
                "-vf", vf,
                "-an",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "27",
                str(dst),
            ])

            paths.append(dst)

        listing = folder / "clips.txt"

        listing.write_text(
            "".join(
                f"file '{p.name}'\n"
                for p in paths
            )
        )

        merged = folder / "merged.mp4"

        run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(listing),
            "-c", "copy",
            str(merged),
        ])

        if not music:
            return merged.read_bytes()

        suffix = Path(music.name).suffix.lower()

        if suffix not in (".mp3", ".wav", ".m4a"):
            suffix = ".mp3"

        audio = folder / ("sound" + suffix)
        audio.write_bytes(music.getvalue())

        final = folder / "final.mp4"

        run([
            "ffmpeg", "-y",
            "-i", str(merged),
            "-i", str(audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(final),
        ])

        return final.read_bytes()


st.title("🎬 KarmaClip Studio")

st.markdown(
    '<div class="kc-sub">'
    "Une idée → une image → une vidéo → ton clip"
    "</div>",
    unsafe_allow_html=True,
)

with st.expander("📁 Mon projet et sauvegarde"):
    st.text_input(
        "Nom du projet",
        key="kc_project",
    )

    st.download_button(
        "💾 Sauvegarder mon projet",
        export_project(),
        file_name="KarmaClip_projet.zip",
        mime="application/zip",
        use_container_width=True,
    )

    restore = st.file_uploader(
        "Restaurer un projet ZIP",
        type=["zip"],
        key="restore_upload",
    )

    if restore:
        def do_restore():
            try:
                import_project(
                    st.session_state.restore_upload.getvalue()
                )
                st.session_state.kc_notice = (
                    "Projet restauré."
                )
            except Exception as e:
                st.session_state.kc_notice = (
                    f"Erreur de restauration : {e}"
                )

        st.button(
            "Restaurer ce projet",
            on_click=do_restore,
            use_container_width=True,
        )

    st.button(
        "🧹 Nouveau projet",
        on_click=reset,
        use_container_width=True,
    )

if st.session_state.get("kc_notice"):
    st.info(
        st.session_state.pop("kc_notice")
    )

st.radio(
    "Étapes",
    STEPS,
    key="kc_step",
    horizontal=True,
    label_visibility="collapsed",
)

st.divider()


# ======================================================
# 1. IMAGE
# ======================================================

if st.session_state.kc_step == STEPS[0]:

    st.header("🎨 Ton image")

    st.caption(
        "Décris ton idée une fois : "
        "elle suivra automatiquement ton projet."
    )

    st.text_area(
        "Que veux-tu créer ?",
        key="kc_idea",
        height=110,
        placeholder=(
            "Un tigre au regard intense, "
            "dans une forêt brumeuse…"
        ),
    )

    a, b = st.columns(2)

    with a:
        st.selectbox(
            "Style",
            [
                "Cinématographique",
                "Photoréaliste",
                "Anime / manga",
                "Fantastique",
                "Illustration",
                "Vintage",
                "Noir et blanc",
            ],
            key="kc_style",
        )

    with b:
        st.selectbox(
            "Format",
            list(SIZES),
            key="kc_format",
        )

    with st.expander(
        "🎵 Paroles ou histoire (facultatif)"
    ):
        st.text_area(
            "Paroles de la chanson",
            key="kc_lyrics",
            height=160,
        )

    st.subheader("✨ Préparer mon image IA")

    st.session_state.kc_image_prompt = (
        image_prompt()
    )

    st.code(
        st.session_state.kc_image_prompt,
        language=None,
    )

    st.caption(
        "La création IA se fait encore sur un site "
        "externe ; le prompt est prêt à copier."
    )

    st.link_button(
        "🎨 Ouvrir Bing Image Creator",
        "https://www.bing.com/images/create",
        use_container_width=True,
    )

    st.subheader("📸 Importer ou retoucher mon image")

    uploaded = st.file_uploader(
        "Choisir une image ou une photo",
        type=["png", "jpg", "jpeg", "webp"],
        key="image_upload",
    )

    if uploaded:
        try:
            original = load(
                uploaded.getvalue()
            )

            with st.expander(
                "🎛️ Retouches (facultatif)"
            ):
                brightness = st.slider(
                    "Luminosité",
                    0.2, 2.0, 1.0, 0.1,
                )

                contrast = st.slider(
                    "Contraste",
                    0.2, 2.0, 1.0, 0.1,
                )

                saturation = st.slider(
                    "Couleurs",
                    0.0, 2.0, 1.0, 0.1,
                )

                blur = st.slider(
                    "Flou",
                    0.0, 4.0, 0.0, 0.5,
                )

                bw = st.checkbox(
                    "Noir et blanc"
                )

            result = ImageEnhance.Brightness(
                original
            ).enhance(brightness)

            result = ImageEnhance.Contrast(
                result
            ).enhance(contrast)

            result = ImageEnhance.Color(
                result
            ).enhance(saturation)

            if bw:
                result = ImageOps.grayscale(
                    result
                ).convert("RGB")

            if blur:
                result = result.filter(
                    ImageFilter.GaussianBlur(blur)
                )

            result = ImageOps.fit(
                result,
                SIZES[st.session_state.kc_format],
                method=Image.Resampling.LANCZOS,
            )

            st.image(
                result,
                caption="Aperçu",
                use_container_width=True,
            )

            ready = png(result)

            st.download_button(
                "⬇️ Télécharger cette image",
                ready,
                file_name="KarmaClip_image.png",
                mime="image/png",
                use_container_width=True,
            )

            if st.button(
                "✅ Utiliser cette image dans mon clip",
                type="primary",
                use_container_width=True,
            ):
                st.session_state.kc_image = ready

                st.success(
                    "Image sélectionnée et conservée "
                    "pour la vidéo !"
                )

        except Exception as e:
            st.error(
                f"Image impossible à ouvrir : {e}"
            )

    if st.session_state.kc_image:
        st.success("Image du projet prête")

        st.image(
            st.session_state.kc_image,
            width=240,
        )

    with st.expander(
        "🎵 Option pochette de single"
    ):
        st.text_input(
            "Titre du single",
            key="kc_title",
        )

        st.text_input(
            "Nom de l’artiste",
            key="kc_artist",
        )

        st.caption(
            "Pour une pochette, sélectionne le "
            "format carré avant d’importer ton image."
        )

    a, b = st.columns(2)

    with a:
        nav(
            "✍️ Créer le prompt",
            STEPS[1],
            False,
        )

    with b:
        nav(
            "🎥 Passer à la vidéo",
            STEPS[2],
        )


# ======================================================
# 2. PROMPT
# ======================================================

elif st.session_state.kc_step == STEPS[1]:

    st.header("✍️ Ton prompt vidéo")

    st.caption(
        "Tout est prérempli avec ton idée. "
        "Ajuste seulement ce que tu veux."
    )

    if st.session_state.kc_image:
        st.image(
            st.session_state.kc_image,
            width=230,
        )

    st.text_area(
        "Description de la scène",
        key="kc_idea",
        height=110,
    )

    st.text_input(
        "Mouvement du sujet",
        key="kc_movement",
    )

    with st.expander(
        "🎬 Réalisation et réglages"
    ):
        st.selectbox(
            "Mouvement de caméra",
            [
                "Travelling lent",
                "Caméra fixe",
                "Travelling avant",
                "Travelling arrière",
                "Rotation autour du sujet",
                "Caméra à l’épaule",
            ],
            key="kc_camera",
        )

        st.selectbox(
            "Ambiance",
            [
                "Cinématographique",
                "Festive",
                "Dynamique",
                "Mystérieuse",
                "Épique",
                "Romantique",
                "Naturelle",
            ],
            key="kc_mood",
        )

        st.selectbox(
            "Durée (secondes)",
            [3, 4, 5, 6, 8, 10],
            key="kc_duration",
        )

        st.checkbox(
            "Conserver visage, vêtements et décor",
            key="kc_continuity",
        )

    if st.button(
        "✨ Composer / actualiser le prompt",
        use_container_width=True,
    ):
        st.session_state.kc_video_prompt = (
            video_prompt()
        )

    if not st.session_state.kc_video_prompt:
        st.session_state.kc_video_prompt = (
            video_prompt()
        )

    st.text_area(
        "Prompt final (modifiable)",
        key="kc_video_prompt",
        height=210,
    )

    with st.expander(
        "🎞️ Storyboard : scènes de 5 secondes"
    ):
        st.caption(
            "Découpe les paroles ou ton scénario "
            "en scènes successives."
        )

        count = st.number_input(
            "Nombre de scènes",
            min_value=1,
            max_value=60,
            value=6,
        )

        if st.button(
            "Créer les scènes",
            use_container_width=True,
        ):
            st.session_state.kc_scenes = (
                build_scenes(
                    st.session_state.kc_lyrics
                    or st.session_state.kc_idea,
                    int(count),
                )
            )

        for i, scene in enumerate(
            st.session_state.kc_scenes
        ):
            with st.expander(
                f"Scène {i + 1} · 5 s"
            ):
                new = st.text_area(
                    "Action",
                    value=scene["description"],
                    key=f"scene_edit_{i}",
                )

                st.session_state.kc_scenes[i][
                    "description"
                ] = new

                st.code(
                    video_prompt(new),
                    language=None,
                )

    nav(
        "🎥 Continuer vers la vidéo",
        STEPS[2],
    )


# ======================================================
# 3. VIDEO
# ======================================================

elif st.session_state.kc_step == STEPS[2]:

    st.header("🎥 Créer ta vidéo")

    st.caption(
        "LoreMotion d’abord, WAN ou NiftyVid "
        "si nécessaire."
    )

    if st.session_state.kc_image:
        st.image(
            st.session_state.kc_image,
            caption="Ton image de référence",
            width=300,
        )

        st.download_button(
            "⬇️ Récupérer l’image pour le moteur",
            st.session_state.kc_image,
            file_name="KarmaClip_reference.png",
            mime="image/png",
            use_container_width=True,
        )

    else:
        st.info(
            "Aucune image enregistrée. "
            "Tu peux créer une vidéo à partir du texte."
        )

    st.selectbox(
        "Choisir un moteur",
        list(ENGINES),
        key="kc_engine",
    )

    st.link_button(
        "🚀 Ouvrir directement le générateur "
        + st.session_state.kc_engine,
        ENGINES[st.session_state.kc_engine],
        use_container_width=True,
    )

    st.caption(
        "Le navigateur ou l’application associée "
        "s’ouvrira selon Android. Le remplissage "
        "automatique du site externe n’est pas disponible."
    )

    st.subheader("✍️ Prompt prêt à utiliser")

    if not st.session_state.kc_video_prompt:
        st.session_state.kc_video_prompt = (
            video_prompt()
        )

    st.text_area(
        "Prompt conservé du projet",
        key="kc_video_prompt",
        height=200,
    )

    st.caption(
        "Tu peux sélectionner le texte pour le copier "
        "dans le générateur externe."
    )

    if st.session_state.kc_scenes:
        with st.expander(
            "🎞️ Mes prompts scène par scène"
        ):
            for i, scene in enumerate(
                st.session_state.kc_scenes
            ):
                st.markdown(
                    f"**Scène {i + 1}**"
                )

                st.code(
                    video_prompt(
                        scene["description"]
                    ),
                    language=None,
                )

    with st.expander("ℹ️ À savoir"):
        st.write(
            "Les générateurs sont des services "
            "indépendants. Leurs quotas et leurs "
            "modalités peuvent évoluer. Aucun "
            "abonnement ou paiement n’est lancé "
            "depuis KarmaClip."
        )

    nav(
        "🎞️ Passer au montage",
        STEPS[3],
    )


# ======================================================
# 4. MONTAGE
# ======================================================

else:

    st.header("🎞️ Monter ton clip")

    st.caption(
        "Importe les scènes MP4 dans l’ordre "
        "souhaité et ajoute la musique."
    )

    clips = st.file_uploader(
        "Mes vidéos MP4",
        type=["mp4"],
        accept_multiple_files=True,
        key="montage_clips",
    )

    if clips:
        for i, f in enumerate(clips):
            with st.expander(
                f"Scène {i + 1} — {f.name}"
            ):
                st.video(f)

    music = st.file_uploader(
        "Musique (facultative)",
        type=["mp3", "wav", "m4a"],
        key="montage_music",
    )

    if music:
        st.audio(music)

    fmt = st.selectbox(
        "Format de sortie",
        [
            "Vertical 9:16",
            "Carré 1:1",
            "Paysage 16:9",
        ],
    )

    formats = {
        "Vertical 9:16": (720, 1280),
        "Carré 1:1": (1080, 1080),
        "Paysage 16:9": (1280, 720),
    }

    ready = bool(
        shutil.which("ffmpeg")
    )

    if not ready:
        st.warning(
            "FFmpeg est absent du serveur. "
            "Le montage ne peut pas démarrer."
        )

    if st.button(
        "🎬 Assembler mon clip",
        type="primary",
        use_container_width=True,
        disabled=not clips or not ready,
    ):
        try:
            with st.spinner(
                "Assemblage du clip…"
            ):
                st.session_state.kc_final = (
                    montage(
                        clips,
                        music,
                        formats[fmt],
                    )
                )

            st.success(
                "Ton clip est prêt !"
            )

        except Exception as e:
            st.error(
                f"Échec du montage : {e}"
            )

    if st.session_state.kc_final:
        st.video(
            st.session_state.kc_final
        )

        st.download_button(
            "⬇️ Télécharger mon MP4",
            st.session_state.kc_final,
            file_name="KarmaClip_final.mp4",
            mime="video/mp4",
            use_container_width=True,
        )

st.divider()

st.caption(
    "KarmaClip Studio · "
    "Image → Prompt → Vidéo → Montage"
)
