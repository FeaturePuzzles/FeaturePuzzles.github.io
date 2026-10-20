import sys, os
from PIL import Image
figs, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
f2 = Image.open(os.path.join(figs, "FeaturePuzzlesPipeline.png")).convert("RGB")
f3 = Image.open(os.path.join(figs, "NetworkPipeline.jpg")).convert("RGB")
def save(im, box, name, w=None):
    c = im.crop(tuple(int(round(v)) for v in box))
    if w and c.width > w: c = c.resize((w, round(c.height * w / c.width)), Image.LANCZOS)
    c.save(os.path.join(out, name), quality=88); return c.size
print(save(f2, (10, 12, 330, 249), "parent.jpg"))
print(save(f2, (407, 26, 722, 264), "parent_crops.jpg"))
print(save(f2, (766, 16, 1064, 274), "aug3d.jpg"))
print(save(f2, (1103, 28, 1415, 265), "sam.jpg"))
print(save(f2, (1423, 28, 1731, 265), "dino.jpg"))
for r, (y0, y1) in enumerate([(340, 526), (533, 717), (724, 902)]):
    for i in range(8):
        x0 = 192 + 187.5 * i
        save(f2, (x0 + 1, y0, x0 + 182, y1), f"tile_{'rgb mask feat'.split()[r]}_{i+1}.jpg")
s = 2.5
def b(x0, y0, x1, y1): return (x0 * s, y0 * s, x1 * s, y1 * s)
print(save(f3, b(140, 94, 366, 313), "net_input.jpg", 600))
print(save(f3, b(1494, 14, 1874, 246), "net_pointcloud.jpg", 900))
for k, x in enumerate([1494, 1643, 1791]):
    save(f3, b(x + 2, 335, x + 128, 461), f"net_mask_{k+1}.jpg", 320)
for k, x in enumerate([1489, 1638, 1788]):
    save(f3, b(x + 2, 622, x + 132, 753), f"net_feat_{k+1}.jpg", 320)
for k, x in enumerate([1485, 1633, 1782]):
    save(f3, b(x + 2, 895, x + 135, 1028), f"net_ov_{k+1}.jpg", 320)
