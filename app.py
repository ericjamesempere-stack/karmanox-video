
# ============================================================
# KARMACLIP — ETAPE 1 : STUDIO IMAGE
# A placer juste apres st.set_page_config(...)
# ============================================================

import io
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

if "kc_image_validated" not in st.session_state:
    st.session_state.kc_image_validated = False

st.title("🎨 KarmaClip — Studio Image")

image_tab, next_tab = st.tabs([
    "1 · Créer / modifier une image",
    "2 · Continuer vers la vidéo"
])

with image_tab:
    st.subheader("Création de l'image")

    description = st.text_area(
        "Décris l'image que tu veux créer",
        placeholder="Un tigre majestueux, regard intense, "
                    "ambiance cinématographique...",
        height=110,
        key="image_description"
    )

    format_choice = st.radio(
        "Format",
        ["Clip vertical 9:16", "Pochette carrée 1:1"],
        horizontal=True,
        key="image_format"
    )

    style = st.selectbox(
        "Style visuel",
        [
            "Photoréaliste",
            "Cinématographique",
            "Anime / Manga",
            "Illustration artistique",
            "Surréaliste",
            "Vintage",
            "Minimaliste"
        ],
        key="image_style"
    )

    reference = st.file_uploader(
        "Importer une photo ou une image (facultatif)",
        type=["png", "jpg", "jpeg", "webp"],
        key="image_reference"
    )

    if description.strip():
        ratio = "9:16" if "9:16" in format_choice else "1:1"

        prompt_image = (
            f"Create a high-quality original image. "
            f"Subject: {description.strip()}. "
            f"Visual style: {style}. "
            f"Aspect ratio: {ratio}. "
            "Detailed composition, beautiful lighting, "
            "coherent anatomy, sharp details. "
            "No text, no watermark."
        )

        st.text_area(
            "Prompt image prêt à copier",
            value=prompt_image,
            height=140,
            key="image_prompt_output"
        )

        st.info(
            "Le prompt est prêt. La génération d'une image "
            "entièrement nouvelle nécessite encore la "
            "connexion d'un moteur IA."
        )

        st.link_button(
            "🎨 Ouvrir un générateur d'images",
            "https://www.bing.com/images/create",
            use_container_width=True
        )

    if reference is not None:
        try:
            source = Image.open(
                io.BytesIO(reference.getvalue())
            )
            source = ImageOps.exif_transpose(source)
            source = source.convert("RGB")

            st.subheader("Retoucher l'image")

            brightness = st.slider(
                "Luminosité", 0.2, 2.0, 1.0, 0.1,
                key="image_brightness"
            )

            contrast = st.slider(
                "Contraste", 0.2, 2.0, 1.0, 0.1,
                key="image_contrast"
            )

            color = st.slider(
                "Couleurs", 0.0, 2.0, 1.0, 0.1,
                key="image_color"
            )

            sharpness = st.slider(
                "Netteté", 0.0, 3.0, 1.0, 0.1,
                key="image_sharpness"
            )

            rotation = st.selectbox(
                "Rotation",
                [0, 90, 180, 270],
                key="image_rotation"
            )

            image = source.rotate(rotation, expand=True)

            image = ImageEnhance.Brightness(
                image
            ).enhance(brightness)

            image = ImageEnhance.Contrast(
                image
            ).enhance(contrast)

            image = ImageEnhance.Color(
                image
            ).enhance(color)

            image = ImageEnhance.Sharpness(
                image
            ).enhance(sharpness)

            if "9:16" in format_choice:
                target_size = (1080, 1920)
            else:
                target_size = (3000, 3000)

            image = ImageOps.fit(
                image,
                target_size,
                method=Image.Resampling.LANCZOS
            )

            st.image(
                image,
                caption="Aperçu de ton image",
                use_container_width=True
            )

            output = io.BytesIO()
            image.save(output, format="PNG")
            image_bytes = output.getvalue()

            st.download_button(
                "💾 Enregistrer l'image",
                data=image_bytes,
                file_name="KarmaClip_image.png",
                mime="image/png",
                use_container_width=True
            )

            if st.button(
                "✅ Valider cette image et continuer",
                use_container_width=True,
                key="image_validate"
            ):
                st.session_state.kc_image_bytes = image_bytes
                st.session_state.kc_image_validated = True
                st.success(
                    "Image conservée dans le projet. "
                    "Ouvre l'onglet 2 pour continuer."
                )

        except Exception as error:
            st.error(f"Impossible de traiter l'image : {error}")

with next_tab:
    if st.session_state.kc_image_validated:
        st.success("Image validée et prête pour la suite.")
        st.image(
            st.session_state.kc_image_bytes,
            width=240
        )
    else:
        st.info(
            "Tu peux continuer sans image ou revenir "
            "à l'étape 1."
        )

    if st.button(
        "🎬 Passer à la préparation vidéo",
        use_container_width=True,
        key="kc_go_video"
    ):
        st.session_state.kc_show_video = True

# On masque l'ancienne interface tant que l'utilisateur
# n'a pas demandé de passer à la vidéo.
if not st.session_state.get("kc_show_video", False):
    st.stop()

st.divider()
st.info(
    "Étape vidéo : tu retrouves ci-dessous les outils "
    "déjà présents dans KarmaClip."
)
