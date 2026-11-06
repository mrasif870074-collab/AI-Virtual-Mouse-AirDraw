
import cv2
import mediapipe as mp
import pyautogui
import math
import time
import os
import ctypes
import tkinter as tk
import numpy as np

from tkinter import filedialog
from pynput import keyboard


# ==========================================================
# AI VIRTUAL MOUSE + FULL DESKTOP AIRDRAW
# Created by: Asif Raza
# Windows 11
# ==========================================================

CAMERA_INDEX = 0

SMOOTHING = 0.40

LEFT_PINCH = 0.060
RIGHT_PINCH = 0.065
MIDDLE_PINCH = 0.065

DRAG_HOLD_SECONDS = 0.50
DOUBLE_CLICK_SECONDS = 0.32

SCROLL_SENSITIVITY = 1400

DRAW_WIDTH = 6
ERASER_WIDTH = 35

TRANSPARENT_COLOR = "#010203"

COLORS = {
    "1": ("White", "#FFFFFF", (255, 255, 255)),
    "2": ("Green", "#00FF00", (0, 255, 0)),
    "3": ("Red", "#FF0000", (0, 0, 255)),
    "4": ("Blue", "#0000FF", (255, 0, 0)),
    "5": ("Yellow", "#FFFF00", (0, 255, 255)),
}

state = {
    "running": True,
    "draw_mode": False,
    "eraser": False,
    "clear": False,
    "save": False,
    "show_camera": True,
    "color_key": "2",
}


# ==========================================================
# HELPERS
# ==========================================================

def distance_between(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def finger_up(lm, tip, pip):
    return lm[tip].y < lm[pip].y


def clamp(value, low, high):
    return max(low, min(value, high))


# ==========================================================
# KEYBOARD CONTROLS
# ==========================================================

def on_key_press(key):

    try:
        char = key.char.lower()

        if char == "d":
            state["draw_mode"] = not state["draw_mode"]
            print("AIR DRAW:", state["draw_mode"])

        elif char == "e":
            state["eraser"] = not state["eraser"]
            print("ERASER:", state["eraser"])

        elif char == "c":
            state["clear"] = True

        elif char == "s":
            state["save"] = True

        elif char == "p":
            state["show_camera"] = not state["show_camera"]

        elif char in COLORS:
            state["color_key"] = char
            print("COLOR:", COLORS[char][0])

        elif char == "q":
            state["running"] = False

    except AttributeError:

        if key == keyboard.Key.esc:
            state["running"] = False


# ==========================================================
# CAMERA
# ==========================================================

def open_camera():

    for index in [CAMERA_INDEX, 1]:

        for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF]:

            print("Trying camera:", index)

            cap = cv2.VideoCapture(index, backend)

            if cap.isOpened():

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                for _ in range(5):

                    success, frame = cap.read()

                    if success and frame is not None:
                        print("Camera connected:", index)
                        return cap

                cap.release()

            else:
                cap.release()

    return None


# ==========================================================
# DESKTOP OVERLAY
# ==========================================================

def create_overlay(screen_w, screen_h):

    root = tk.Tk()

    root.title("AI AirDraw Overlay")
    root.overrideredirect(True)

    root.geometry(f"{screen_w}x{screen_h}+0+0")

    root.configure(bg=TRANSPARENT_COLOR)

    root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
    root.attributes("-topmost", True)

    canvas = tk.Canvas(
        root,
        width=screen_w,
        height=screen_h,
        bg=TRANSPARENT_COLOR,
        highlightthickness=0,
        bd=0
    )

    canvas.pack(fill="both", expand=True)

    root.update_idletasks()
    root.update()

    user32 = ctypes.windll.user32

    hwnd = root.winfo_id()
    hwnd = user32.GetParent(hwnd) or hwnd

    GWL_EXSTYLE = -20

    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080

    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

    style |= (
        WS_EX_LAYERED
        | WS_EX_TRANSPARENT
        | WS_EX_TOOLWINDOW
    )

    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    user32.SetWindowPos(
        hwnd,
        -1,
        0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0010 | 0x0020
    )

    root.update()

    return root, canvas


# ==========================================================
# WEBCAM WINDOW
# ==========================================================

def camera_to_front(title):

    user32 = ctypes.windll.user32

    hwnd = user32.FindWindowW(None, title)

    if hwnd:

        user32.SetWindowPos(
            hwnd,
            -1,
            0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0010
        )


# ==========================================================
# AIR DRAW
# ==========================================================

def draw_segment(canvas, p1, p2, color, width):

    canvas.create_line(
        p1[0], p1[1],
        p2[0], p2[1],
        fill=color,
        width=width,
        capstyle=tk.ROUND,
        joinstyle=tk.ROUND,
        tags=("stroke",)
    )


def draw_dot(canvas, point, color, width):

    radius = max(2, width // 2)

    canvas.create_oval(
        point[0] - radius,
        point[1] - radius,
        point[0] + radius,
        point[1] + radius,
        fill=color,
        outline=color,
        tags=("stroke",)
    )


def erase_area(canvas, x, y):

    radius = ERASER_WIDTH // 2

    items = canvas.find_overlapping(
        x - radius,
        y - radius,
        x + radius,
        y + radius
    )

    for item in items:

        if "stroke" in canvas.gettags(item):
            canvas.delete(item)


# ==========================================================
# SAVE DRAWING
# ==========================================================

def save_drawing(strokes, screen_w, screen_h):

    filename = filedialog.asksaveasfilename(
        title="Save AirDraw",
        defaultextension=".png",
        initialfile="AirDraw.png",
        filetypes=[("PNG Image", "*.png")]
    )

    if not filename:
        return

    image = np.full(
        (screen_h, screen_w, 3),
        255,
        dtype=np.uint8
    )

    for stroke in strokes:

        points = stroke["points"]

        if not points:
            continue

        color = (
            (255, 255, 255)
            if stroke["erase"]
            else stroke["bgr"]
        )

        width = (
            ERASER_WIDTH
            if stroke["erase"]
            else DRAW_WIDTH
        )

        if len(points) == 1:

            cv2.circle(
                image,
                points[0],
                max(2, width // 2),
                color,
                -1
            )

        else:

            for i in range(1, len(points)):

                cv2.line(
                    image,
                    points[i - 1],
                    points[i],
                    color,
                    width,
                    cv2.LINE_AA
                )

    if cv2.imwrite(filename, image):
        print("Drawing saved:", filename)
    else:
        print("Save failed.")


# ==========================================================
# MAIN PROGRAM
# ==========================================================

def main():

    if os.name != "nt":
        print("Windows required.")
        return

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.01

    camera = None
    root = None
    hands = None
    listener = None

    dragging = False

    try:

        # --------------------------------------
        # CAMERA
        # --------------------------------------

        camera = open_camera()

        if camera is None:

            print("Camera not available.")
            print("Close other camera applications.")
            return

        screen_w, screen_h = pyautogui.size()

        webcam_title = "AI Virtual Mouse - Webcam"

        cv2.namedWindow(
            webcam_title,
            cv2.WINDOW_NORMAL
        )

        cv2.resizeWindow(
            webcam_title,
            400,
            300
        )

        cv2.moveWindow(
            webcam_title,
            max(0, screen_w - 420),
            max(0, screen_h - 340)
        )

        # --------------------------------------
        # MEDIAPIPE
        # --------------------------------------

        mp_hands = mp.solutions.hands
        draw_utils = mp.solutions.drawing_utils

        hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55
        )

        # --------------------------------------
        # OVERLAY
        # --------------------------------------

        root, canvas = create_overlay(
            screen_w,
            screen_h
        )

        camera_to_front(webcam_title)

        listener = keyboard.Listener(
            on_press=on_key_press
        )

        listener.start()

        # --------------------------------------
        # MOUSE STATE
        # --------------------------------------

        smooth_x = screen_w // 2
        smooth_y = screen_h // 2

        previous_left_pinch = False
        previous_right_pinch = False
        previous_middle_pinch = False

        left_pinch_start = None
        previous_scroll_y = None

        last_click_time = 0
        pending_single_click = False

        previous_point = None
        active_stroke = None

        strokes = []

        camera_visible = True

        print("\n===================================")
        print(" AI VIRTUAL MOUSE + AIRDRAW")
        print("===================================")

        print("INDEX FINGER       = MOVE")
        print("THUMB + INDEX      = LEFT CLICK")
        print("DOUBLE PINCH       = DOUBLE CLICK")
        print("HOLD PINCH         = DRAG")
        print("THUMB + MIDDLE     = RIGHT CLICK")
        print("THUMB + RING       = MIDDLE CLICK")
        print("INDEX + MIDDLE UP  = SCROLL")

        print("-----------------------------------")

        print("D = DRAW MODE")
        print("E = ERASER")
        print("1-5 = COLORS")
        print("C = CLEAR")
        print("S = SAVE")
        print("P = CAMERA")
        print("Q / ESC = EXIT")

        print("===================================")

        # ======================================
        # MAIN LOOP
        # ======================================

        while state["running"]:

            ok, frame = camera.read()

            if not ok or frame is None:
                print("Camera frame error.")
                break

            frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            result = hands.process(rgb)

            status = "MOUSE MODE"

            now = time.monotonic()

            # ----------------------------------
            # CAMERA VISIBILITY
            # ----------------------------------

            if state["show_camera"] != camera_visible:

                camera_visible = state["show_camera"]

                cv2.setWindowProperty(
                    webcam_title,
                    cv2.WND_PROP_VISIBLE,
                    1 if camera_visible else 0
                )

                if camera_visible:
                    camera_to_front(webcam_title)

            # ----------------------------------
            # CLEAR
            # ----------------------------------

            if state["clear"]:

                canvas.delete("stroke")
                canvas.delete("cursor")

                strokes.clear()

                previous_point = None
                active_stroke = None

                state["clear"] = False

                print("Drawing cleared.")

            # ----------------------------------
            # SAVE
            # ----------------------------------

            if state["save"]:

                state["save"] = False

                save_drawing(
                    strokes,
                    screen_w,
                    screen_h
                )

                root.attributes("-topmost", True)

            # ----------------------------------
            # HAND DETECTION
            # ----------------------------------

            if result.multi_hand_landmarks:

                hand = result.multi_hand_landmarks[0]
                lm = hand.landmark

                draw_utils.draw_landmarks(
                    frame,
                    hand,
                    mp_hands.HAND_CONNECTIONS
                )

                thumb = lm[4]
                index = lm[8]
                middle = lm[12]
                ring = lm[16]

                index_up = finger_up(lm, 8, 6)
                middle_up = finger_up(lm, 12, 10)
                ring_up = finger_up(lm, 16, 14)
                pinky_up = finger_up(lm, 20, 18)

                # ==================================
                # AIR DRAW MODE
                # ==================================

                if state["draw_mode"]:

                    previous_left_pinch = False
                    previous_right_pinch = False
                    previous_middle_pinch = False

                    left_pinch_start = None
                    previous_scroll_y = None
                    pending_single_click = False

                    if dragging:
                        pyautogui.mouseUp()
                        dragging = False

                    drawing_gesture = (
                        index_up
                        and not middle_up
                        and not ring_up
                        and not pinky_up
                    )

                    if drawing_gesture:

                        x = clamp(
                            int(index.x * screen_w),
                            0,
                            screen_w - 1
                        )

                        y = clamp(
                            int(index.y * screen_h),
                            0,
                            screen_h - 1
                        )

                        current_point = (x, y)

                        if state["eraser"]:

                            current_color = "#FFFFFF"
                            current_bgr = (255, 255, 255)
                            current_width = ERASER_WIDTH

                        else:

                            (
                                _,
                                current_color,
                                current_bgr
                            ) = COLORS[state["color_key"]]

                            current_width = DRAW_WIDTH

                        if previous_point is None:

                            active_stroke = {
                                "points": [current_point],
                                "bgr": current_bgr,
                                "erase": state["eraser"]
                            }

                            strokes.append(active_stroke)

                            if state["eraser"]:
                                erase_area(canvas, x, y)

                            else:
                                draw_dot(
                                    canvas,
                                    current_point,
                                    current_color,
                                    current_width
                                )

                        else:

                            if state["eraser"]:

                                erase_area(canvas, x, y)

                            else:

                                draw_segment(
                                    canvas,
                                    previous_point,
                                    current_point,
                                    current_color,
                                    current_width
                                )

                            if active_stroke is not None:
                                active_stroke["points"].append(
                                    current_point
                                )

                        previous_point = current_point

                        canvas.delete("cursor")

                        canvas.create_oval(
                            x - 7,
                            y - 7,
                            x + 7,
                            y + 7,
                            outline="white",
                            width=2,
                            tags=("cursor",)
                        )

                        status = (
                            "ERASING"
                            if state["eraser"]
                            else "DRAWING"
                        )

                    else:

                        previous_point = None
                        active_stroke = None

                        canvas.delete("cursor")

                        status = "RAISE INDEX TO DRAW"

                # ==================================
                # NORMAL MOUSE MODE
                # ==================================

                else:

                    canvas.delete("cursor")

                    target_x = clamp(
                        int(index.x * screen_w),
                        0,
                        screen_w - 1
                    )

                    target_y = clamp(
                        int(index.y * screen_h),
                        0,
                        screen_h - 1
                    )

                    smooth_x = int(
                        SMOOTHING * target_x
                        + (1 - SMOOTHING) * smooth_x
                    )

                    smooth_y = int(
                        SMOOTHING * target_y
                        + (1 - SMOOTHING) * smooth_y
                    )

                    left_pinch = (
                        distance_between(thumb, index)
                        < LEFT_PINCH
                    )

                    right_pinch = (
                        distance_between(thumb, middle)
                        < RIGHT_PINCH
                    )

                    middle_pinch = (
                        distance_between(thumb, ring)
                        < MIDDLE_PINCH
                    )

                    scroll_mode = (
                        index_up
                        and middle_up
                        and not ring_up
                        and not pinky_up
                        and not left_pinch
                        and not right_pinch
                    )

                    # ----------------------------------
                    # SCROLL
                    # ----------------------------------

                    if scroll_mode:

                        current_y = (
                            index.y + middle.y
                        ) / 2

                        if previous_scroll_y is not None:

                            delta = previous_scroll_y - current_y

                            if abs(delta) > 0.008:

                                amount = int(
                                    delta * SCROLL_SENSITIVITY
                                )

                                amount = clamp(amount, -8, 8)

                                if amount:
                                    pyautogui.scroll(amount)

                        previous_scroll_y = current_y

                        if dragging:
                            pyautogui.mouseUp()
                            dragging = False

                        previous_left_pinch = False
                        previous_right_pinch = False
                        previous_middle_pinch = False

                        left_pinch_start = None

                        status = "SCROLLING"

                    else:

                        previous_scroll_y = None

                        # ----------------------------------
                        # MOVE CURSOR
                        # ----------------------------------

                        pyautogui.moveTo(
                            smooth_x,
                            smooth_y
                        )

                        status = "MOVE CURSOR"

                        # ----------------------------------
                        # LEFT CLICK / DOUBLE CLICK / DRAG
                        # ----------------------------------

                        if left_pinch:

                            if not previous_left_pinch:
                                left_pinch_start = now

                            held_for = (
                                now - left_pinch_start
                                if left_pinch_start is not None
                                else 0
                            )

                            if (
                                held_for >= DRAG_HOLD_SECONDS
                                and not dragging
                            ):

                                # Cancel pending single click.
                                pending_single_click = False

                                pyautogui.mouseDown()
                                dragging = True

                            if dragging:
                                status = "DRAGGING"

                            else:
                                status = "LEFT PINCH"

                        else:

                            if dragging:

                                pyautogui.mouseUp()
                                dragging = False

                                status = "DROP"

                            elif previous_left_pinch:

                                release_time = now

                                if (
                                    release_time - last_click_time
                                    <= DOUBLE_CLICK_SECONDS
                                ):

                                    pending_single_click = False

                                    pyautogui.doubleClick(
                                        interval=0.08
                                    )

                                    last_click_time = 0

                                    status = "DOUBLE CLICK"

                                else:

                                    pending_single_click = True
                                    last_click_time = release_time

                            left_pinch_start = None

                        # Perform delayed single click only when
                        # the double-click interval has expired.
                        if (
                            pending_single_click
                            and now - last_click_time
                            > DOUBLE_CLICK_SECONDS
                            and not left_pinch
                        ):

                            pyautogui.click()

                            pending_single_click = False

                            status = "LEFT CLICK"

                        previous_left_pinch = left_pinch

                        # ----------------------------------
                        # RIGHT CLICK
                        # ----------------------------------

                        if (
                            right_pinch
                            and not previous_right_pinch
                            and not left_pinch
                            and not dragging
                        ):

                            pending_single_click = False

                            pyautogui.rightClick()

                            status = "RIGHT CLICK"

                        previous_right_pinch = right_pinch

                        # ----------------------------------
                        # MIDDLE CLICK
                        # ----------------------------------

                        if (
                            middle_pinch
                            and not previous_middle_pinch
                            and not left_pinch
                            and not right_pinch
                            and not dragging
                        ):

                            pending_single_click = False

                            pyautogui.middleClick()

                            status = "MIDDLE CLICK"

                        previous_middle_pinch = middle_pinch

            # ==================================
            # NO HAND DETECTED
            # ==================================

            else:

                previous_scroll_y = None

                previous_left_pinch = False
                previous_right_pinch = False
                previous_middle_pinch = False

                left_pinch_start = None

                previous_point = None
                active_stroke = None

                canvas.delete("cursor")

                if dragging:

                    pyautogui.mouseUp()
                    dragging = False

                # Complete a pending single click.
                if pending_single_click:

                    if now - last_click_time > DOUBLE_CLICK_SECONDS:

                        pyautogui.click()

                        pending_single_click = False

                status = "NO HAND DETECTED"

            # ==================================
            # CAMERA DISPLAY
            # ==================================

            cv2.putText(
                frame,
                status,
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "D: Draw | E: Eraser | Q: Quit",
                (15, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 0),
                1
            )

            if camera_visible:

                cv2.imshow(
                    webcam_title,
                    frame
                )

            # ==================================
            # DESKTOP HUD
            # ==================================

            canvas.delete("hud")

            mode_text = (
                "AIR DRAW ON"
                if state["draw_mode"]
                else "MOUSE MODE"
            )

            eraser_text = (
                "ERASER ON"
                if state["eraser"]
                else "ERASER OFF"
            )

            color_name = COLORS[state["color_key"]][0]

            canvas.create_rectangle(
                10, 10, 390, 175,
                fill="#111827",
                outline="#00FFAA",
                width=2,
                tags=("hud",)
            )

            hud_lines = [
                ("AI VIRTUAL MOUSE + AIRDRAW", "#00FFAA"),
                (f"STATUS: {status}", "white"),
                (f"{mode_text} | {eraser_text}", "#FFFF00"),
                (f"COLOR: {color_name}", "white"),
                ("D: Draw | E: Eraser | C: Clear", "#00FFAA"),
                ("S: Save | P: Camera | Q: Exit", "#00FFAA"),
                ("Pinch: Click | Hold: Drag", "#00FFAA"),
            ]

            for i, (line, color) in enumerate(hud_lines):

                canvas.create_text(
                    25,
                    25 + i * 21,
                    text=line,
                    fill=color,
                    anchor="nw",
                    font=("Arial", 10, "bold"),
                    tags=("hud",)
                )

            # ==================================
            # UPDATE
            # ==================================

            root.update_idletasks()
            root.update()

            key = cv2.waitKey(1) & 0xFF

            if key == 27:
                state["running"] = False

    except pyautogui.FailSafeException:

        print("PyAutoGUI emergency stop.")

    except Exception as error:

        print("PROGRAM ERROR:", repr(error))

    finally:

        if dragging:

            try:
                pyautogui.mouseUp()
            except Exception:
                pass

        if listener is not None:
            listener.stop()

        if camera is not None:
            camera.release()

        if hands is not None:
            hands.close()

        if root is not None:

            try:
                root.destroy()
            except Exception:
                pass

        cv2.destroyAllWindows()

        print("AI Virtual Mouse stopped.")


if __name__ == "__main__":
    main()

