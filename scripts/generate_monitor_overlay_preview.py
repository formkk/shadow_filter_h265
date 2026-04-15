import os
import cv2
import numpy as np
from datetime import datetime


def create_preview_image(output_path: str):
    frame = np.zeros((720, 720, 3), dtype=np.uint8)

    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    fps_str = f"ENC FPS: {24.0:4.1f}"

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    thickness = 1
    margin = 10
    color = (255, 255, 255)

    ts_size = cv2.getTextSize(ts_str, font, font_scale, thickness)[0]
    fps_size = cv2.getTextSize(fps_str, font, font_scale, thickness)[0]
    max_w = max(ts_size[0], fps_size[0])
    total_h = ts_size[1] + fps_size[1] + 10
    base_x = frame.shape[1] - max_w - margin
    base_y = frame.shape[0] - margin

    cv2.rectangle(
        frame,
        (base_x - 5, base_y - total_h - 5),
        (base_x + max_w + 5, base_y + 5),
        (0, 0, 0),
        -1,
    )

    y_fps = base_y - ts_size[1] - 5
    cv2.putText(frame, fps_str, (base_x, y_fps), font, font_scale, color, thickness)
    cv2.putText(frame, ts_str, (base_x, base_y), font, font_scale, color, thickness)

    cv2.putText(frame, "Monitor Overlay Preview", (20, 40), font, 0.8, (200, 200, 200), 2)
    cv2.putText(frame, "This is a static preview image", (20, 70), font, 0.6, (180, 180, 180), 1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, frame)
    return output_path


if __name__ == "__main__":
    out = os.path.join("docs", "monitor_overlay_preview.png")
    path = create_preview_image(out)
    print(f"Preview image generated: {path}")

