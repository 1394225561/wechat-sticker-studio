"""Draw the original wave fixture. The committed PNGs are ready to compose."""

from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 4
INK = "#2a2743"
GOLD = "#ffcd61"
HONEY = "#f59b43"
CREAM = "#f8f4ff"
PLUM = "#7663b9"
POSES = [
    (180, 167), (197, 150), (202, 123), (202, 95),
    (192, 77), (207, 85), (211, 104), (204, 86),
    (193, 81), (203, 113), (199, 142), (186, 161),
]


def draw_frame(hand):
    image = Image.new("RGBA", (240 * SCALE, 240 * SCALE))
    draw = ImageDraw.Draw(image)

    def rect(box, radius, color):
        draw.rounded_rectangle(tuple(value * SCALE for value in box), radius * SCALE,
                               fill=color, outline=INK, width=4 * SCALE)

    def circle(x, y, radius, color, outline=None):
        box = ((x - radius) * SCALE, (y - radius) * SCALE,
               (x + radius) * SCALE, (y + radius) * SCALE)
        draw.ellipse(box, fill=color, outline=outline, width=3 * SCALE)

    def line(points, width, color):
        draw.line([(x * SCALE, y * SCALE) for x, y in points], fill=color,
                  width=width * SCALE, joint="curve")

    elbow = (174 + (hand[0] - 180) // 3, min(154, hand[1] + 32))
    for points in ([(78, 137), (58, 152), (53, 168)], [(148, 137), elbow, hand]):
        line(points, 17, INK)
        line(points, 9, PLUM)
        circle(*points[-1], 13, GOLD, INK)

    rect((78, 166, 105, 201), 9, PLUM)
    rect((119, 166, 146, 201), 9, PLUM)
    rect((74, 190, 106, 207), 7, HONEY)
    rect((118, 190, 151, 207), 7, HONEY)
    rect((73, 111, 152, 182), 22, HONEY)
    rect((91, 138, 133, 166), 9, GOLD)
    circle(106, 152, 4, PLUM)
    circle(119, 152, 4, PLUM)

    line([(111, 68), (111, 43)], 7, INK)
    circle(111, 42, 8, GOLD, INK)
    rect((52, 64, 172, 132), 24, GOLD)
    rect((69, 76, 155, 117), 17, CREAM)
    for x in (91, 133):
        circle(x, 94, 5, INK)
        circle(x, 105, 4, "#f2a5b0")
    line([(105, 100), (109, 104), (115, 104), (119, 100)], 3, INK)
    return image.resize((240, 240), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    frames = Path(__file__).resolve().parent / "frames"
    frames.mkdir(exist_ok=True)
    for index, hand in enumerate(POSES, 1):
        draw_frame(hand).save(frames / f"{index:02}.png")
