import os
import tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence

# Совместимость MoviePy 1.0.3 с новыми версиями Pillow (где удалили Image.ANTIALIAS)
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

import streamlit as st
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    ImageSequenceClip,
    concatenate_videoclips,
    vfx,
)

st.set_page_config(
    page_title="GIF → TikTok / Shorts Studio",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- МОБИЛЬНАЯ АДАПТАЦИЯ И СТИЛИ ---
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 3rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 780px;
        }
        .stButton > button {
            border-radius: 12px;
            height: 3.1rem;
            font-weight: 600;
            font-size: 1rem;
        }
        .stDownloadButton > button {
            border-radius: 12px;
            height: 3.1rem;
            font-weight: 600;
        }
        @media (max-width: 640px) {
            h1 {
                font-size: 1.65rem !important;
            }
            h2, h3 {
                font-size: 1.2rem !important;
            }
            .stMarkdown p {
                font-size: 0.95rem;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎬 GIF → TikTok / Shorts Studio")
st.caption("Склейка нескольких GIF, бесшовный цикл, текст/хук, музыка и водяной знак.")


def load_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        test_line = f"{current} {word}"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test_line
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def create_hook_text_image(
    text: str,
    canvas_w: int,
    font_size: int = 54,
    text_color: str = "#FFFFFF",
    box_bg: bool = True,
) -> np.ndarray:
    """Рендерит многострочный текст / заголовок с переносом строк и опциональной плашкой."""
    font = load_font(font_size)
    dummy = Image.new("RGBA", (canvas_w, 200))
    draw = ImageDraw.Draw(dummy)
    max_text_w = int(canvas_w * 0.82)
    lines = wrap_text(draw, text.strip(), font, max_text_w)
    if not lines:
        lines = [text.strip()]

    line_height = int(font_size * 1.28)
    pad_x = 32
    pad_y = 22

    widest = 0
    for line in lines:
        b = draw.textbbox((0, 0), line, font=font)
        widest = max(widest, b[2] - b[0])

    box_w = min(canvas_w - 40, widest + pad_x * 2)
    box_h = len(lines) * line_height + pad_y * 2

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if box_bg:
        draw.rounded_rectangle(
            [(0, 0), (box_w, box_h)],
            radius=24,
            fill=(15, 15, 20, 205),
        )

    y = pad_y
    for line in lines:
        b = draw.textbbox((0, 0), line, font=font)
        lw = b[2] - b[0]
        x = (box_w - lw) // 2
        if not box_bg:
            draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 210))
        draw.text((x, y), line, font=font, fill=text_color)
        y += line_height

    return np.array(img)


def create_text_watermark(text: str, opacity: float) -> np.ndarray:
    font = load_font(38)
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0] + 24, bbox[3] - bbox[1] + 24

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    alpha = int(255 * opacity)
    draw.text((12, 12), text, font=font, fill=(0, 0, 0, alpha))
    draw.text((10, 10), text, font=font, fill=(255, 255, 255, alpha))
    return np.array(img)


def make_blurred_background(frame: np.ndarray, target_w: int = 1080, target_h: int = 1920) -> np.ndarray:
    pil_img = Image.fromarray(frame)
    bg = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=35))
    dark_overlay = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    bg = Image.blend(bg, dark_overlay, alpha=0.35)
    return np.array(bg)


def load_gif_clip(gif_path: str, loop_mode: str, target_size: tuple[int, int] | None = None) -> ImageSequenceClip:
    """Читает кадры GIF через Pillow, собирает цикл и при необходимости приводит к общему размеру."""
    with Image.open(gif_path) as im:
        durations_ms = []
        pil_frames = []
        for frame in ImageSequence.Iterator(im):
            durations_ms.append(frame.info.get("duration", 100))
            pil_frames.append(frame.convert("RGB"))

    if not pil_frames:
        raise ValueError("Не удалось прочитать кадры из GIF-файла.")

    if target_size is not None:
        tw, th = target_size
        pil_frames = [
            f.resize((tw, th), Image.Resampling.LANCZOS) if f.size != (tw, th) else f
            for f in pil_frames
        ]

    rgb_frames = [np.array(f) for f in pil_frames]

    avg_duration_ms = sum(durations_ms) / len(durations_ms) if durations_ms else 100.0
    if avg_duration_ms < 20:
        avg_duration_ms = 100.0
    fps = max(8.0, min(30.0, 1000.0 / avg_duration_ms))

    if loop_mode == "Ping-Pong (Бумеранг)" and len(rgb_frames) > 2:
        sequence = rgb_frames + rgb_frames[-2:0:-1]
    elif loop_mode == "Ping-Pong (Бумеранг)" and len(rgb_frames) == 2:
        sequence = rgb_frames + [rgb_frames[0]]
    else:
        sequence = rgb_frames

    return ImageSequenceClip(sequence, fps=fps)


def build_combined_gif_clip(gif_paths: list[str], loop_mode: str):
    """Склеивает несколько GIF в один клип с общим размером кадров для безопасного concatenate."""
    sizes = []
    for p in gif_paths:
        with Image.open(p) as im:
            sizes.append(im.size)

    # Берём максимальные размеры среди загруженных GIF, чтобы ничего не обрезалось на этапе склейки
    common_w = max(w for w, _ in sizes)
    common_h = max(h for _, h in sizes)
    common_size = (common_w, common_h)

    clips = [load_gif_clip(p, loop_mode, target_size=common_size) for p in gif_paths]
    if len(clips) == 1:
        return clips[0]

    # Приводим клипы к единому FPS перед конкатенацией
    target_fps = max(c.fps for c in clips)
    normalized = [c.set_fps(target_fps) for c in clips]
    return concatenate_videoclips(normalized, method="compose")


# --- 1. ЗАГРУЗКА ФАЙЛОВ ---
st.subheader("1. Файлы")
gif_files = st.file_uploader(
    "GIF-анимации (можно выбрать сразу несколько)",
    type=["gif"],
    accept_multiple_files=True,
)
if gif_files:
    st.caption(f"Выбрано GIF: {len(gif_files)} шт. — они будут идти по очереди в загруженном порядке.")

audio_file = st.file_uploader("Аудиодорожка (MP3 / WAV)", type=["mp3", "wav"])

# --- 2. ЦИКЛ, ФОРМАТ И ДЛИТЕЛЬНОСТЬ ---
st.subheader("2. Цикл и формат")
loop_mode = st.selectbox(
    "Бесшовный цикл каждого GIF",
    ["Ping-Pong (Бумеранг)", "Обычный повтор (Loop)"],
    help="Ping-Pong проигрывает каждый GIF вперед и назад перед переходом к следующему.",
)
format_mode = st.selectbox(
    "Формат кадра",
    [
        "9:16 (TikTok / Shorts) с размытым фоном",
        "9:16 (Заполнение / Crop)",
        "Оригинальный размер",
    ],
)
motion_mode = st.selectbox(
    "Движение камеры",
    ["Без дополнительного зума", "Плавный зум (Ken Burns)"],
    help="Добавляет легкое приближение во время ролика, чтобы картинка выглядела живее.",
)

duration_mode = st.selectbox("Длительность видео", ["По длине аудио", "Фиксированная (сек)"])
custom_duration = 15
if duration_mode == "Фиксированная (сек)" or audio_file is None:
    custom_duration = st.slider("Длительность (сек)", min_value=3, max_value=60, value=15)

# --- 3. НАСТРОЙКИ АУДИО ---
audio_volume = 0.85
audio_start_sec = 0
if audio_file is not None:
    st.subheader("3. Настройки звука")
    audio_volume = st.slider("Громкость трека", min_value=0.0, max_value=1.5, value=0.85, step=0.05)
    audio_start_sec = st.slider("Старт трека с секунды", min_value=0, max_value=60, value=0)

# --- 4. ТЕКСТ / ЗАГОЛОВОК ДЛЯ ШОРТС ---
st.subheader("4. Текст и хук на видео")
enable_caption = st.checkbox("Добавить текст / заголовок поверх видео", value=False)
caption_text = ""
caption_pos = "top"
caption_color = "#FFFFFF"
caption_box = True
caption_size = 52

if enable_caption:
    caption_text = st.text_area(
        "Текст на экране",
        placeholder="Например: Когда забыл сохранить проект перед выключением света...",
        height=85,
    )
    caption_pos = st.selectbox("Позиция текста", ["top", "center", "bottom"])
    caption_color = st.color_picker("Цвет текста", "#FFFFFF")
    caption_box = st.checkbox("Темная подложка под текст", value=True)
    caption_size = st.slider("Размер шрифта", min_value=28, max_value=84, value=52)

# --- 5. ВОДЯНОЙ ЗНАК ---
st.subheader("5. Водяной знак")
wm_type = st.radio(
    "Источник водяного знака",
    ["Без водяного знака", "Текст", "Картинка (PNG)"],
    horizontal=True,
)
wm_text = ""
wm_image = None
wm_opacity = 0.7
wm_position = "bottom-right"

if wm_type != "Без водяного знака":
    if wm_type == "Текст":
        wm_text = st.text_input("Текст водяного знака", value="@my_channel")
    else:
        wm_image = st.file_uploader("Логотип PNG", type=["png"])
    wm_position = st.selectbox(
        "Позиция знака",
        ["bottom-right", "bottom-left", "top-right", "top-left", "center"],
    )
    wm_opacity = st.slider("Прозрачность знака", min_value=0.1, max_value=1.0, value=0.7)

st.divider()

# --- 6. РЕНДЕР ---
if st.button("🚀 Сгенерировать видео", type="primary", use_container_width=True):
    if not gif_files:
        st.error("Сначала загрузите хотя бы один GIF-файл.")
        st.stop()

    if len(gif_files) > 10:
        st.warning("Для стабильной работы на бесплатном сервере выберите до 10 GIF за один запуск.")
        st.stop()

    with st.spinner("Собираем ролик из GIF... Обычно это занимает 15–50 секунд."):
        with tempfile.TemporaryDirectory() as tmpdir:
            gif_paths = []
            for idx, gf in enumerate(gif_files):
                p = os.path.join(tmpdir, f"input_{idx}.gif")
                with open(p, "wb") as f:
                    f.write(gf.read())
                gif_paths.append(p)

            base_loop = build_combined_gif_clip(gif_paths, loop_mode)

            # Аудио и длительность
            audio_clip = None
            if audio_file is not None:
                audio_path = os.path.join(tmpdir, "audio_input")
                with open(audio_path, "wb") as f:
                    f.write(audio_file.read())
                audio_clip = AudioFileClip(audio_path)

            if duration_mode == "По длине аудио" and audio_clip is not None:
                available_audio = max(1.0, audio_clip.duration - float(audio_start_sec))
                target_duration = min(60.0, available_audio)
            else:
                target_duration = float(custom_duration)

            video = base_loop.fx(vfx.loop, duration=target_duration)

            # Форматирование под 9:16 или оригинал
            if format_mode == "9:16 (TikTok / Shorts) с размытым фоном":
                target_w, target_h = 1080, 1920
                bg_clip = video.fl_image(lambda img: make_blurred_background(img, target_w, target_h))
                fg_clip = video.resize(width=target_w)
                if fg_clip.h > target_h:
                    fg_clip = video.resize(height=target_h)
                video = CompositeVideoClip(
                    [bg_clip, fg_clip.set_position("center")],
                    size=(target_w, target_h),
                )
            elif format_mode == "9:16 (Заполнение / Crop)":
                target_w, target_h = 1080, 1920
                video = video.resize(height=target_h)
                if video.w < target_w:
                    video = video.resize(width=target_w)
                video = video.crop(
                    x_center=video.w / 2,
                    y_center=video.h / 2,
                    width=target_w,
                    height=target_h,
                )

            # Плавный зум
            if motion_mode == "Плавный зум (Ken Burns)" and target_duration > 0:
                video = video.resize(lambda t: 1.0 + 0.08 * (t / target_duration))
                video = CompositeVideoClip([video.set_position("center")], size=(video.w, video.h))

            layers = [video]

            # Текст / хук поверх видео
            if enable_caption and caption_text.strip():
                cap_arr = create_hook_text_image(
                    text=caption_text,
                    canvas_w=video.w,
                    font_size=caption_size,
                    text_color=caption_color,
                    box_bg=caption_box,
                )
                cap_clip = ImageClip(cap_arr).set_duration(target_duration)
                y_pos_map = {
                    "top": int(video.h * 0.12),
                    "center": int((video.h - cap_clip.h) * 0.5),
                    "bottom": int(video.h * 0.76 - cap_clip.h * 0.5),
                }
                layers.append(cap_clip.set_position(("center", y_pos_map[caption_pos])))

            # Водяной знак
            wm_clip = None
            if wm_type == "Текст" and wm_text.strip():
                wm_arr = create_text_watermark(wm_text, wm_opacity)
                wm_clip = ImageClip(wm_arr).set_duration(target_duration)
            elif wm_type == "Картинка (PNG)" and wm_image is not None:
                wm_path = os.path.join(tmpdir, "wm.png")
                with open(wm_path, "wb") as f:
                    f.write(wm_image.read())
                wm_clip = (
                    ImageClip(wm_path)
                    .resize(width=max(80, int(video.w * 0.24)))
                    .set_opacity(wm_opacity)
                    .set_duration(target_duration)
                )

            if wm_clip is not None:
                margin = 36
                pos_map = {
                    "bottom-right": (video.w - wm_clip.w - margin, video.h - wm_clip.h - margin),
                    "bottom-left": (margin, video.h - wm_clip.h - margin),
                    "top-right": (video.w - wm_clip.w - margin, margin),
                    "top-left": (margin, margin),
                    "center": ("center", "center"),
                }
                layers.append(wm_clip.set_position(pos_map[wm_position]))

            final_video = CompositeVideoClip(layers)

            if audio_clip is not None:
                start_t = min(float(audio_start_sec), max(0.0, audio_clip.duration - 0.5))
                end_t = min(audio_clip.duration, start_t + target_duration)
                trimmed_audio = (
                    audio_clip.subclip(start_t, end_t)
                    .volumex(audio_volume)
                    .audio_fadeout(1.0)
                )
                final_video = final_video.set_audio(trimmed_audio)

            output_path = os.path.join(tmpdir, "shorts_output.mp4")
            final_video.write_videofile(
                output_path,
                fps=24,
                codec="libx264",
                audio_codec="aac",
                preset="fast",
                logger=None,
            )

            with open(output_path, "rb") as f:
                video_bytes = f.read()

            st.success("Видео готово!")
            st.video(video_bytes)
            st.download_button(
                label="⬇️ Скачать MP4",
                data=video_bytes,
                file_name="tiktok_shorts_video.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
