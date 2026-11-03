import io
import base64
import requests
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title='KarmaClip AI V10', page_icon='🎬', layout='wide')
if "visual_reference_description" not in st.session_state:
    st.session_state.visual_reference_description = ""

st.title('🎬 KarmaClip AI V10')
st.caption('Paroles + musique → scènes de 5 secondes → vidéos → clip final')

SERVICES = {
    'Lore Motion (prioritaire)': 'https://loremotion.com/',
    'Wan2.Video': 'https://wan2.video/',
    'Wan AI': 'https://wan.video/',
    'LTX / Hugging Face': 'https://huggingface.co/spaces/Lightricks/ltx-video-distilled',
    'NiftyVid': 'https://igorcsis.github.io/nifty-vid/',
    'NOVA AI Video': 'https://novaos-original.github.io/nova-os-website/video-studio/ai-generator.html',
    'Kling': 'https://app.klingai.com/global/',
    'Vidu': 'https://www.vidu.com/',
    'Veo': 'https://labs.google/fx/tools/flow',
}
STYLES = ['Cinématique photoréaliste', 'Clip musical', 'Animation 3D', 'Fantastique', 'Vintage', 'Minimaliste']
RATIOS = {'Vertical 9:16': (360, 640), 'Horizontal 16:9': (640, 360), 'Carré 1:1': (512, 512)}
SCENE_SECONDS = 5

if 'scenes' not in st.session_state:
    st.session_state.scenes = []
if 'clip' not in st.session_state:
    st.session_state.clip = None


def ffmpeg_available():
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def audio_duration(raw, extension):
    if not raw:
        return None
    if extension == '.wav':
        try:
            import wave
            with wave.open(io.BytesIO(raw), 'rb') as source:
                return source.getnframes() / source.getframerate()
        except Exception:
            pass
    if not ffmpeg_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ('audio' + extension)
        source.write_bytes(raw)
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(source)],
            capture_output=True, text=True, timeout=40,
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None


@st.cache_resource(show_spinner="Chargement du modèle de vision gratuit…")
def load_free_vision():
    """Run a public, open-weight image captioner locally; no API key or account."""
    from transformers import BlipProcessor, BlipForConditionalGeneration
    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
    model.eval()
    return processor, model


def describe_image_free(image_bytes):
    """Offline inference after first model download; no third-party paid API."""
    from PIL import Image
    import torch
    processor, model = load_free_vision()
    picture = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    picture.thumbnail((512, 512))
    inputs = processor(images=picture, return_tensors="pt")
    with torch.inference_mode():
        ids = model.generate(**inputs, max_new_tokens=55, num_beams=3)
    caption = processor.decode(ids[0], skip_special_tokens=True).strip()
    if not caption:
        raise ValueError("Le modèle n'a pas pu décrire cette image.")
    return caption


def describe_image(image_bytes, mime):
    """Optional richer vision with a separately configured API key."""
    key = st.secrets.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Aucune clé OPENAI_API_KEY configurée.")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                "Describe the main visible subjects in this image accurately in concise English. "
                "Count them and identify their colors, outfits, relative positions, setting and "
                "distinguishing features. Do not invent details. Max 65 words."
            )},
            {"type": "image_url", "image_url": {
                "url": f"data:{mime};base64,{encoded}", "detail": "low"
            }}
        ]}],
        "max_tokens": 140
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload, timeout=45
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()



def scene_mood(lyrics, index, count):
    """Mood is a creative cue, not a literal restatement of lyrics."""
    t = lyrics.lower()
    if any(w in t for w in ["love", "amour", "heart", "coeur", "cœur", "kiss", "together"]):
        return "romantic"
    if any(w in t for w in ["alone", "lonely", "sad", "lost", "triste", "seul", "oubli"]):
        return "melancholic"
    if any(w in t for w in ["party", "dance", "danse", "groove", "move", "fiesta"]):
        return "dance"
    if any(w in t for w in ["fight", "fire", "rage", "combat", "liberty", "liberté"]):
        return "power"
    return "dreamlike"


# Original short-film beats, not lyrics pasted into a prompt.
BEATS = {
    "dance": [
        "The characters notice each other across the dance floor, exchanging shy glances while keeping their distance",
        "Both characters begin a playful synchronized step, still dancing separately",
        "One character makes a funny exaggerated move; the other answers with a teasing dance move",
        "They circle each other in rhythm, smiling, without touching",
        "Their movements become confident and perfectly synchronized",
        "They reach toward one another and finally join hands, dancing together",
    ],
    "romantic": [
        "The characters exchange a hesitant look, as if recognizing a familiar feeling",
        "One character takes a small step closer; the other responds with a warm smile",
        "They move around each other in a playful, gentle rhythm",
        "A quiet pause brings their faces close; their expressions become sincere",
        "They move side by side, naturally matching each other's pace",
        "They join hands and share a joyful, spontaneous dance",
    ],
    "melancholic": [
        "The character pauses in the middle of an ordinary action, distracted by a distant memory",
        "A small object catches the character's attention; they turn it slowly in their hands",
        "The character walks past familiar surroundings, noticing what has changed",
        "They stop, look back briefly, then decide to keep moving",
        "The character lifts their head and takes a more determined step",
        "They continue forward with a subtle, genuine smile",
    ],
    "power": [
        "The character plants their feet firmly and faces an unexpected challenge",
        "They move forward with a steady, purposeful stride",
        "A sudden obstacle forces a quick, energetic reaction",
        "The character recovers balance and responds with renewed confidence",
        "They make one decisive movement that changes the situation",
        "The character stands tall, breathing deeply after the effort",
    ],
    "dreamlike": [
        "The character notices a small unexpected detail in the surroundings and turns toward it",
        "They follow the detail with curiosity, moving through the space",
        "An unusual visual change surprises the character; they react naturally",
        "They experiment with their surroundings in a playful, physical way",
        "The character makes a confident choice and changes direction",
        "The scene ends with a distinctive gesture that can connect to the next shot",
    ],
}


def image_guided_prompt(scene, style, reference_description, custom_idea="", mood="dreamlike",
                        total_scenes=1, story_idea=""):
    """Direct a visible physical action. Lyrics inform mood, not the literal text."""
    index = int(scene.get("index", 0))
    beats = BEATS.get(mood, BEATS["dreamlike"])
    if total_scenes <= 1:
        beat = beats[0]
    else:
        beat_index = min(len(beats)-1, round(index * (len(beats)-1) / (total_scenes-1)))
        beat = beats[beat_index]
    variation = [
        "A gentle tracking shot follows the movement",
        "The camera slowly moves closer as the gesture unfolds",
        "A side-angle shot emphasizes body language",
        "The camera holds steady on the characters' reaction",
        "A low-angle shot highlights the physical movement",
        "The camera follows a small change in direction",
    ][index % 6]
    action = (custom_idea or (beat + ". " + variation)).strip()
    action = re.sub(r"\\s+", " ", action)[:330]
    subjects = reference_description.strip()
    if subjects:
        identity = f"Use the uploaded reference image. Same exact subjects: {subjects}. "
        identity += "Keep the exact number of characters, faces, outfits, and colors. "
    else:
        identity = ("Use the uploaded reference image as the character and setting reference. "
                    "Do not invent or remove subjects. ")
    setting = (story_idea.strip()[:140] + ". ") if story_idea.strip() else ""
    return (f"{identity}{setting}Action: {action}. "
            f"One clear physical action, expressive natural movement, {style}, "
            "single continuous shot, no captions, no new characters.")


def create_scenes(lyrics, duration, style, ratio, idea, scene_length=5):
    lines = [line.strip() for line in lyrics.splitlines()
             if line.strip() and not re.match(r'^\\[.*\\]$', line.strip())]
    count = min(240, max(1, math.ceil(duration / scene_length)))
    result = []
    for index in range(count):
        start = index * scene_length
        end = min(duration, start + scene_length)
        first = math.floor(index * len(lines) / count)
        last = max(first + 1, math.ceil((index + 1) * len(lines) / count))
        excerpt = ' / '.join(lines[first:last]) if lines else ""
        result.append({'index': index, 'start': start, 'end': end, 'lyrics': excerpt,
                       'prompt': '', 'scene_idea': '', 'image': None, 'video': None,
                       'last_frame': None, 'engine': next(iter(SERVICES))})
    return result


def creative_storyboard_with_ai(scenes, lyrics, reference_description, idea, style, image_bytes=None, mime=None):
    """Optional AI director. Image supplied to vision model when configured."""
    key = st.secrets.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Le réalisateur IA nécessite une clé API configurée.")
    image_part = []
    if image_bytes:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        image_part = [{"type": "image_url", "image_url": {
            "url": f"data:{mime or 'image/jpeg'};base64,{encoded}", "detail": "low"
        }}]
    brief = (
        "You are an inventive music-video director. Create a coherent visual narrative "
        "with concrete actions by the EXACT characters in the reference image. "
        "Never paraphrase, illustrate literally, quote or repeat song lyrics. "
        "Translate the song's emotional journey into a playful, meaningful sequence of "
        "VISUAL ACTIONS and evolving character relationships. "
        "Respect all subjects, exact character count, outfits and appearance. "
        "Each shot is about 5 seconds, a single physically achievable action. "
        "Prompts concise (max 42 words), in English, visually specific, different "
        "from one another, no text overlays. "
        "Return ONLY JSON object with key 'prompts' holding an array of strings, "
        f"exactly {len(scenes)} items.\n"
        f"Characters description: {reference_description}\n"
        f"Creative direction: {idea}\nStyle: {style}\n"
        f"Lyrics (for emotional arc only): {lyrics[:11000]}\n"
        f"Scene excerpts: {json.dumps([x['lyrics'] for x in scenes], ensure_ascii=False)}"
    )
    payload = {"model": "gpt-4o-mini", "messages": [
        {"role": "user", "content": [{"type": "text", "text": brief}] + image_part}
    ], "response_format": {"type": "json_object"}, "max_tokens": min(12000, max(1500, len(scenes)*85))}
    response = requests.post("https://api.openai.com/v1/chat/completions",
                             headers={"Authorization": f"Bearer {key}"},
                             json=payload, timeout=120)
    response.raise_for_status()
    prompts = json.loads(response.json()["choices"][0]["message"]["content"])["prompts"]
    if len(prompts) != len(scenes) or not all(isinstance(p,str) for p in prompts):
        raise ValueError("Le réalisateur IA n'a pas renvoyé le bon nombre de scènes.")
    return prompts


def extract_last_frame(raw, extension):
    if not ffmpeg_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ('scene' + extension)
        target = Path(tmp) / 'last.png'
        source.write_bytes(raw)
        run = subprocess.run(
            ['ffmpeg', '-y', '-sseof', '-0.08', '-i', str(source),
             '-frames:v', '1', str(target)],
            capture_output=True, timeout=60,
        )
        if run.returncode == 0 and target.exists():
            return target.read_bytes()
    return None


def generate_ltx_scene(prompt):
    """Try public LTX Gradio endpoints; fail visibly if incompatible."""
    from gradio_client import Client
    client = Client("Lightricks/ltx-video-distilled")
    errors = []
    for endpoint in ("/generate_video", "/generate"):
        try:
            result = client.predict(prompt=prompt, api_name=endpoint)
            def find_video(item):
                if isinstance(item, str):
                    path = Path(item)
                    if path.is_file() and path.suffix.lower() in (".mp4", ".webm"):
                        return path.read_bytes(), path.suffix.lower()
                if isinstance(item, dict):
                    for value in item.values():
                        found = find_video(value)
                        if found:
                            return found
                if isinstance(item, (list, tuple)):
                    for value in item:
                        found = find_video(value)
                        if found:
                            return found
                return None
            found = find_video(result)
            if found:
                return found
            errors.append(f"{endpoint}: no downloadable video returned")
        except Exception as exc:
            errors.append(f"{endpoint}: {str(exc)[:220]}")
    raise RuntimeError("LTX public interface unavailable: " + " | ".join(errors))


def assemble_clip(scenes, music, music_ext, ratio):
    if not ffmpeg_available():
        raise RuntimeError('FFmpeg et FFprobe sont nécessaires sur le serveur.')
    if not scenes or any(scene['video'] is None for scene in scenes):
        raise RuntimeError('Chaque scène doit avoir une vidéo importée.')
    width, height = RATIOS[ratio]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        clips = []
        for index, scene in enumerate(scenes):
            data, extension = scene['video']
            source = directory / f'input_{index}{extension}'
            output = directory / f'part_{index}.mp4'
            source.write_bytes(data)
            duration = max(0.1, scene['end'] - scene['start'])
            filters = (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                       f'crop={width}:{height},fps=24,setsar=1,format=yuv420p,'
                       f'tpad=stop_mode=clone:stop_duration={duration}')
            command = ['ffmpeg', '-y', '-i', str(source), '-an', '-vf', filters,
                       '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast',
                       '-crf', '24', '-movflags', '+faststart', str(output)]
            run = subprocess.run(command, capture_output=True, timeout=240)
            if run.returncode != 0:
                raise RuntimeError(f'Erreur de montage scène {index + 1}: '
                                   + run.stderr.decode(errors='replace')[-400:])
            clips.append(output)
        manifest = directory / 'list.txt'
        manifest.write_text(''.join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding='utf-8')
        silent = directory / 'silent.mp4'
        run = subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                              '-i', str(manifest), '-c', 'copy', str(silent)],
                             capture_output=True, timeout=240)
        if run.returncode != 0:
            raise RuntimeError('Assemblage des scènes impossible.')
        if not music:
            return silent.read_bytes()
        audio = directory / ('music' + music_ext)
        audio.write_bytes(music)
        output = directory / 'final.mp4'
        run = subprocess.run(['ffmpeg', '-y', '-i', str(silent), '-i', str(audio),
                              '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                              '-c:a', 'aac', '-b:a', '192k', '-shortest',
                              '-movflags', '+faststart', str(output)],
                             capture_output=True, timeout=240)
        if run.returncode != 0:
            raise RuntimeError('Impossible d’ajouter la musique au clip.')
        return output.read_bytes()


with st.container(border=True):
    st.subheader('1. Ta chanson')
    title = st.text_input('Titre', value='Mon clip')
    artist = st.text_input('Artiste', value='KarManoX')
    lyrics = st.text_area('Paroles complètes', height=180)
    idea = st.text_area('Idée ou scénario du clip (facultatif)', height=90)
    audio_file = st.file_uploader('Musique WAV ou MP3 (facultative)', type=['wav', 'mp3'])
    music = audio_file.getvalue() if audio_file else None
    music_ext = Path(audio_file.name).suffix.lower() if audio_file else ''
    detected = audio_duration(music, music_ext) if music else None
    if detected:
        st.success(f'Durée de la musique : {detected:.1f} secondes')
    manual_duration = st.number_input('Durée si aucune musique disponible (secondes)',
                                      min_value=5, max_value=1200, value=180, step=5)
    duration = detected or float(manual_duration)
    scene_length = st.selectbox("Durée des séquences (secondes)", [5, 3, 4, 6, 8, 10], index=0)
    style = st.selectbox('Style', STYLES)
    ratio = st.selectbox('Format', list(RATIOS))
    reference = st.file_uploader('Image du personnage (facultative)',
                                 type=['png', 'jpg', 'jpeg', 'webp'])
    if reference:
        st.image(reference.getvalue(), width=200)
    st.text_area(
        "🖼️ Description des personnages de l'image (commune à toutes les scènes)",
        placeholder="Ex. Two anthropomorphic bananas: one in a black suit, one in a red evening dress. Both dancing at a party.",
        height=95, key="visual_reference_description"
    )
    if reference:
        st.caption("Analyse gratuite : modèle BLIP local, sans clé API. Le premier lancement télécharge le modèle et peut être lent ou dépasser la mémoire de Streamlit Cloud.")
        col_free, col_plus = st.columns(2)
        with col_free:
            free_click = st.button("🔎 Analyser gratuitement", use_container_width=True)
        with col_plus:
            plus_click = st.button("✨ Analyse avancée (API)", use_container_width=True)
        if free_click:
            try:
                with st.spinner("Analyse de l'image en cours…"):
                    description = describe_image_free(reference.getvalue())
                st.session_state.visual_reference_description = description
                st.success("Description créée. Vérifie le
