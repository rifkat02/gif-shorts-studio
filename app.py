import os
import random
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
st.caption("Склейка GIF, переходы, пресеты хуков и канала, музыка, водяной знак и текст для публикации.")

HOOK_PRESETS = {
    "Свой текст": "",
    "Не делай так…": "Не делай так, если не хочешь потерять результат!",
    "Разбор за 15 секунд": "Разбираем момент за 15 секунд — смотри до конца",
    "Когда пошло не по плану": "Когда всё пошло не по плану в самый неподходящий момент",
    "Итог": "Главный итог, который стоит запомнить",
}

CHANNEL_PRESETS = {
    "Свой выбор": None,
    "TikTok / Shorts (низ-право)": {
        "wm_position": "bottom-right",
        "wm_opacity": 0.72,
        "caption_box": True,
        "caption_pos": "top",
    },
    "Минимализм без плашки": {
        "wm_position": "top-right",
        "wm_opacity": 0.55,
        "caption_box": False,
        "caption_pos": "top",
    },
    "Акцент по центру": {
        "wm_position": "bottom-left",
        "wm_opacity": 0.65,
        "caption_box": True,
        "caption_pos": "center",
    },
}


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


def make_blurred_background(frame: np.ndarray, target_w: int = 720, target_h: int = 1280) -> np.ndarray:
    pil_img = Image.fromarray(np.asarray(frame, dtype=np.uint8)).convert("RGB")
    bg = pil_img.resize((target_w, target_h), Image.Resampling.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=24))
    dark_overlay = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    bg = Image.blend(bg, dark_overlay, alpha=0.35)
    return np.array(bg, dtype=np.uint8)


def load_gif_clip(
    gif_path: str,
    loop_mode: str,
    speed_mult: float = 1.0,
    target_size: tuple[int, int] | None = None,
) -> ImageSequenceClip:
    """Читает кадры GIF через Pillow, собирает цикл, задаёт скорость и размер."""
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
            f.resize((tw, th), Image.Resampling.BILINEAR) if f.size != (tw, th) else f
            for f in pil_frames
        ]

    rgb_frames = [np.array(f, dtype=np.uint8) for f in pil_frames]

    avg_duration_ms = sum(durations_ms) / len(durations_ms) if durations_ms else 100.0
    if avg_duration_ms < 20:
        avg_duration_ms = 100.0
    base_fps = max(8.0, min(24.0, 1000.0 / avg_duration_ms))
    fps = max(6.0, min(30.0, base_fps * float(speed_mult)))

    if loop_mode == "Ping-Pong (Бумеранг)" and len(rgb_frames) > 2:
        sequence = rgb_frames + rgb_frames[-2:0:-1]
    elif loop_mode == "Ping-Pong (Бумеранг)" and len(rgb_frames) == 2:
        sequence = rgb_frames + [rgb_frames[0]]
    else:
        sequence = rgb_frames

    return ImageSequenceClip(sequence, fps=fps)


def build_combined_gif_clip(
    gif_paths: list[str],
    loop_mode: str,
    speed_mult: float = 1.0,
    transition_mode: str = "Без перехода (стык)",
    fade_duration: float = 0.35,
):
    """Склеивает несколько GIF в один клип с общим размером кадров и опциональным crossfade."""
    sizes = []
    for p in gif_paths:
        with Image.open(p) as im:
            sizes.append(im.size)

    common_w = max(w for w, _ in sizes)
    common_h = max(h for _, h in sizes)
    common_size = (common_w, common_h)

    clips = [
        load_gif_clip(p, loop_mode, speed_mult=speed_mult, target_size=common_size)
        for p in gif_paths
    ]
    if len(clips) == 1:
        return clips[0]

    target_fps = max(c.fps for c in clips)
    normalized = [c.set_fps(target_fps) for c in clips]

    if transition_mode == "Плавный crossfade":
        min_dur = min(c.duration for c in normalized)
        safe_fade = round(min(float(fade_duration), max(0.05, min_dur * 0.4)), 3)
        if min_dur > safe_fade * 1.5 and safe_fade > 0:
            faded_clips = [normalized[0]] + [
                c.crossfadein(safe_fade) for c in normalized[1:]
            ]
            return concatenate_videoclips(
                faded_clips,
                padding=-safe_fade,
                method="compose",
            )

    return concatenate_videoclips(normalized, method="compose")


def estimate_render_seconds(
    num_gifs: int,
    duration_sec: float,
    is_full_hd: bool,
    has_zoom: bool,
    has_crossfade: bool,
) -> tuple[int, int]:
    """Возвращает примерный диапазон секунд для сборки на слабом контейнере."""
    base = 6.0 + duration_sec * (1.2 if is_full_hd else 0.55)
    base += max(0, num_gifs - 1) * 1.5
    if has_zoom:
        base *= 1.65
    if has_crossfade and num_gifs > 1:
        base *= 1.15
    low = max(5, int(base * 0.8))
    high = max(low + 5, int(base * 1.35))
    return low, high


def build_publish_copy(hook_text: str, cta_text: str, wm_text: str) -> str:
    main_line = hook_text.strip() if hook_text.strip() else "Короткий ролик из GIF"
    cta_line = cta_text.strip() if cta_text.strip() else ""
    channel_tag = ""
    if wm_text.strip().startswith("@"):
        channel_tag = wm_text.strip().lstrip("@").replace(" ", "")
    tags = ["#shorts", "#tiktok", "#reels", "#gif", "#нарезка", "#тренды"]
    if channel_tag:
        tags.append(f"#{channel_tag}")

    parts = [main_line]
    if cta_line:
        parts.append(cta_line)
    parts.append(" ".join(tags))
    return "\n\n".join(parts)


# --- 1. ЗАГРУЗКА ФАЙЛОВ ---
st.subheader("1. Файлы")
gif_files = st.file_uploader(
    "GIF-анимации (можно выбрать сразу несколько)",
    type=["gif"],
    accept_multiple_files=True,
)
shuffle_gifs = st.checkbox("Перемешать порядок GIF случайно перед сборкой", value=False)
gif_speed = st.select_slider(
    "Скорость воспроизведения GIF",
    options=[0.75, 1.0, 1.25, 1.5],
    value=1.0,
    format_func=lambda x: f"{x}x",
)

total_mb = 0.0
if gif_files:
    total_mb += sum(gf.size for gf in gif_files) / (1024 * 1024)
    st.caption(
        f"Выбрано GIF: {len(gif_files)} шт. | "
        f"{'Порядок перемешается случайно' if shuffle_gifs else 'Порядок по списку'} | "
        f"Темп {gif_speed}x"
    )

audio_file = st.file_uploader("Аудиодорожка (MP3 / WAV)", type=["mp3", "wav"])
if audio_file is not None:
    total_mb += audio_file.size / (1024 * 1024)

# --- 2. ЦИКЛ, ПЕРЕХОДЫ, ФОРМАТ И ДЛИТЕЛЬНОСТЬ ---
st.subheader("2. Цикл, переходы и формат")
channel_preset = st.selectbox("Профиль настроек канала", list(CHANNEL_PRESETS.keys()))
preset_cfg = CHANNEL_PRESETS[channel_preset]

loop_mode = st.selectbox(
    "Бесшовный цикл каждого GIF",
    ["Ping-Pong (Бумеранг)", "Обычный повтор (Loop)"],
    help="Ping-Pong проигрывает каждый GIF вперед и назад перед переходом к следующему.",
)
transition_mode = st.selectbox(
    "Переход между склеенными GIF",
    ["Без перехода (стык)", "Плавный crossfade"],
    help="Crossfade мягко смешивает кадры на стыке GIF без замедления всего остального ролика.",
)
fade_duration = 0.35
if transition_mode == "Плавный crossfade":
    fade_duration = st.slider(
        "Длительность перехода (сек)",
        min_value=0.15,
        max_value=0.80,
        value=0.35,
        step=0.05,
    )

format_mode = st.selectbox(
    "Формат кадра",
    [
        "9:16 (TikTok / Shorts) с размытым фоном",
        "9:16 (Заполнение / Crop)",
        "Оригинальный размер",
    ],
)
quality_mode = st.selectbox(
    "Разрешение и скорость рендера",
    ["720x1280 (Быстрый рендер)", "1080x1920 (Full HD, медленнее)"],
    help="720x1280 рендерится заметно быстрее на бесплатном сервере.",
)
motion_mode = st.selectbox(
    "Движение камеры",
    ["Без дополнительного зума", "Плавный зум (Ken Burns)"],
    help="Плавный зум дополнительно нагружает процессор при рендере каждого кадра.",
)

duration_mode = st.selectbox("Длительность видео", ["По длине аудио", "Фиксированная (сек)"])
custom_duration = 12
if duration_mode == "Фиксированная (сек)" or audio_file is None:
    custom_duration = st.slider("Длительность (сек)", min_value=3, max_value=45, value=12)

# --- 3. НАСТРОЙКИ АУДИО ---
audio_volume = 0.85
audio_start_sec = 0
if audio_file is not None:
    st.subheader("3. Настройки звука")
    audio_volume = st.slider("Громкость трека", min_value=0.0, max_value=1.5, value=0.85, step=0.05)
    audio_start_sec = st.slider("Старт трека с секунды", min_value=0, max_value=60, value=0)

# --- 4. ТЕКСТ / ЗАГОЛОВОК И CTA ДЛЯ ШОРТС ---
st.subheader("4. Текст, хук и призыв к действию")
enable_caption = st.checkbox("Добавить текст / заголовок поверх видео", value=False)
caption_text = ""
cta_text = ""
default_pos = preset_cfg["caption_pos"] if preset_cfg else "top"
default_box = preset_cfg["caption_box"] if preset_cfg else True
caption_pos = default_pos
caption_color = "#FFFFFF"
caption_box = default_box
caption_size = 48
smooth_text_fade = True

if enable_caption:
    hook_preset_choice = st.selectbox("Быстрый пресет хука", list(HOOK_PRESETS.keys()))
    preset_sample = HOOK_PRESETS[hook_preset_choice]
    caption_text = st.text_area(
        "Текст на экране",
        value=preset_sample,
        placeholder="Например: Когда забыл сохранить проект перед выключением света...",
        height=85,
    )
    cta_text = st.text_input(
        "Нижний CTA / титр (необязательно)",
        placeholder="Например: Подпишись, чтобы не пропустить разбор",
    )
    pos_options = ["top", "center", "bottom"]
    caption_pos = st.selectbox(
        "Позиция основного текста",
        pos_options,
        index=pos_options.index(default_pos) if default_pos in pos_options else 0,
    )
    caption_color = st.color_picker("Цвет текста", "#FFFFFF")
    caption_box = st.checkbox("Темная подложка под текст", value=default_box)
    caption_size = st.slider("Размер шрифта", min_value=24, max_value=80, value=48)
    smooth_text_fade = st.checkbox("Плавное появление и затухание текста", value=True)

# --- 5. ВОДЯНОЙ ЗНАК ---
st.subheader("5. Водяной знак")
wm_type = st.radio(
    "Источник водяного знака",
    ["Без водяного знака", "Текст", "Картинка (PNG)"],
    horizontal=True,
)
wm_text = ""
wm_image = None
default_opacity = preset_cfg["wm_opacity"] if preset_cfg else 0.7
default_wm_pos = preset_cfg["wm_position"] if preset_cfg else "bottom-right"
wm_opacity = default_opacity
wm_position = default_wm_pos

if wm_type != "Без водяного знака":
    if wm_type == "Текст":
        wm_text = st.text_input("Текст водяного знака", value="@my_channel")
    else:
        wm_image = st.file_uploader("Логотип PNG", type=["png"])
    wm_pos_options = ["bottom-right", "bottom-left", "top-right", "top-left", "center"]
    wm_position = st.selectbox(
        "Позиция знака",
        wm_pos_options,
        index=wm_pos_options.index(default_wm_pos) if default_wm_pos in wm_pos_options else 0,
    )
    wm_opacity = st.slider("Прозрачность знака", min_value=0.1, max_value=1.0, value=default_opacity)

st.divider()

# --- ОЦЕНКА ВЕСА И ВРЕМЕНИ СБОРКИ ---
approx_dur = float(custom_duration) if (duration_mode == "Фиксированная (сек)" or audio_file is None) else 15.0
est_low, est_high = estimate_render_seconds(
    num_gifs=len(gif_files) if gif_files else 1,
    duration_sec=approx_dur,
    is_full_hd="1080x1920" in quality_mode,
    has_zoom=(motion_mode == "Плавный зум (Ken Burns)"),
    has_crossfade=(transition_mode == "Плавный crossfade"),
)
st.caption(
    f"📦 Размер загруженных файлов: ~{total_mb:.1f} МБ | "
    f"⏱️ Примерное время рендера: {est_low}–{est_high} сек"
)

# --- 6. РЕНДЕР ---
if st.button("🚀 Сгенерировать видео", type="primary", use_container_width=True):
    if not gif_files:
        st.error("Сначала загрузите хотя бы один GIF-файл.")
        st.stop()

    if len(gif_files) > 10:
        st.info(f"Выбрано {len(gif_files)} GIF — рендер может занять больше времени и памяти на бесплатном сервере.")

    status_box = st.empty()
    status_box.info("Шаг 1/3: Читаем GIF и собираем цикл...")

    ordered_gifs = list(gif_files)
    if shuffle_gifs and len(ordered_gifs) > 1:
        random.shuffle(ordered_gifs)

    with tempfile.TemporaryDirectory() as tmpdir:
        gif_paths = []
        for idx, gf in enumerate(ordered_gifs):
            p = os.path.join(tmpdir, f"input_{idx}.gif")
            with open(p, "wb") as f:
                f.write(gf.read())
            gif_paths.append(p)

        base_loop = build_combined_gif_clip(
            gif_paths,
            loop_mode=loop_mode,
            speed_mult=gif_speed,
            transition_mode=transition_mode,
            fade_duration=fade_duration,
        )

        audio_clip = None
        if audio_file is not None:
            audio_path = os.path.join(tmpdir, "audio_input")
            with open(audio_path, "wb") as f:
                f.write(audio_file.read())
            audio_clip = AudioFileClip(audio_path)

        if duration_mode == "По длине аудио" and audio_clip is not None:
            available_audio = max(1.0, audio_clip.duration - float(audio_start_sec))
            target_duration = min(45.0, available_audio)
        else:
            target_duration = float(custom_duration)

        video = base_loop.fx(vfx.loop, duration=target_duration)

        status_box.info("Шаг 2/3: Форматируем кадр и накладываем слои...")
        is_full_hd = "1080x1920" in quality_mode
        target_w, target_h = (1080, 1920) if is_full_hd else (720, 1280)
        out_fps = 24 if is_full_hd else 20

        if format_mode == "9:16 (TikTok / Shorts) с размытым фоном":
            first_frame = video.get_frame(0)
            bg_array = make_blurred_background(first_frame, target_w, target_h)
            bg_clip = ImageClip(bg_array).set_duration(target_duration)

            fg_clip = video.resize(width=target_w)
            if fg_clip.h > target_h:
                fg_clip = video.resize(height=target_h)

            video = CompositeVideoClip(
                [bg_clip, fg_clip.set_position(("center", "center"))],
                size=(target_w, target_h),
            ).set_duration(target_duration)
        elif format_mode == "9:16 (Заполнение / Crop)":
            video = video.resize(height=target_h)
            if video.w < target_w:
                video = video.resize(width=target_w)
            video = video.crop(
                x_center=video.w / 2,
                y_center=video.h / 2,
                width=target_w,
                height=target_h,
            )

        if motion_mode == "Плавный зум (Ken Burns)" and target_duration > 0:
            canvas_w, canvas_h = video.w, video.h
            zoomed = video.resize(lambda t: 1.0 + 0.08 * (t / target_duration))
            video = CompositeVideoClip(
                [zoomed.set_position(("center", "center"))],
                size=(canvas_w, canvas_h),
            ).set_duration(target_duration)

        canvas_w, canvas_h = video.w, video.h
        layers = [video.set_position((0, 0))]

        fade_t = min(0.25, target_duration * 0.15) if smooth_text_fade else 0.0

        # Основной текст / хук поверх видео
        if enable_caption and caption_text.strip():
            cap_arr = create_hook_text_image(
                text=caption_text,
                canvas_w=canvas_w,
                font_size=caption_size,
                text_color=caption_color,
                box_bg=caption_box,
            )
            cap_clip = ImageClip(cap_arr).set_duration(target_duration)
            if fade_t > 0:
                cap_clip = cap_clip.crossfadein(fade_t).crossfadeout(fade_t)
            y_pos_map = {
                "top": int(canvas_h * 0.12),
                "center": int((canvas_h - cap_clip.h) * 0.5),
                "bottom": int(canvas_h * 0.72 - cap_clip.h * 0.5),
            }
            layers.append(cap_clip.set_position(("center", y_pos_map[caption_pos])))

        # Нижний CTA / титр
        if enable_caption and cta_text.strip():
            cta_arr = create_hook_text_image(
                text=cta_text,
                canvas_w=canvas_w,
                font_size=max(22, int(caption_size * 0.68)),
                text_color="#FFE066",
                box_bg=True,
            )
            cta_clip = ImageClip(cta_arr).set_duration(target_duration)
            if fade_t > 0:
                cta_clip = cta_clip.crossfadein(fade_t).crossfadeout(fade_t)
            cta_y = int(canvas_h * 0.82)
            layers.append(cta_clip.set_position(("center", cta_y)))

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
                .resize(width=max(80, int(canvas_w * 0.24)))
                .set_opacity(wm_opacity)
                .set_duration(target_duration)
            )

        if wm_clip is not None:
            margin = 36
            pos_map = {
                "bottom-right": (canvas_w - wm_clip.w - margin, canvas_h - wm_clip.h - margin),
                "bottom-left": (margin, canvas_h - wm_clip.h - margin),
                "top-right": (canvas_w - wm_clip.w - margin, margin),
                "top-left": (margin, margin),
                "center": ("center", "center"),
            }
            layers.append(wm_clip.set_position(pos_map[wm_position]))

        final_video = CompositeVideoClip(layers, size=(canvas_w, canvas_h)).set_duration(target_duration)

        if audio_clip is not None:
            start_t = min(float(audio_start_sec), max(0.0, audio_clip.duration - 0.5))
            end_t = min(audio_clip.duration, start_t + target_duration)
            trimmed_audio = (
                audio_clip.subclip(start_t, end_t)
                .volumex(audio_volume)
                .audio_fadeout(1.0)
            )
            final_video = final_video.set_audio(trimmed_audio)

        status_box.info("Шаг 3/3: Кодируем MP4...")
        output_path = os.path.join(tmpdir, "shorts_output.mp4")
        final_video.write_videofile(
            output_path,
            fps=out_fps,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2,
            logger=None,
        )

        with open(output_path, "rb") as f:
            video_bytes = f.read()

    status_box.empty()
    st.success("Видео готово!")
    st.video(video_bytes)
    st.download_button(
        label="⬇️ Скачать MP4",
        data=video_bytes,
        file_name="tiktok_shorts_video.mp4",
        mime="video/mp4",
        use_container_width=True,
    )

    st.subheader("📋 Готовое описание и хештеги")
    publish_text = build_publish_copy(caption_text, cta_text, wm_text)
    st.code(publish_text, language="text")
