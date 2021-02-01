import numpy as np
import cv2 as cv
from calamari_ocr.ocr.dataset.imageprocessors.data_preprocessor import ImageProcessor


class CenterNormalizer(ImageProcessor):
    @staticmethod
    def default_params() -> dict:
        return {
            'extra_params': (4, 1.0, 0.3),
        }

    def __init__(self, extra_params=(4, 1.0, 0.3), debug=False, **kwargs):
        super().__init__(**kwargs)
        self.debug = debug
        self.target_height = self.params.line_height_
        self.range, self.smoothness, self.extra = extra_params

    def _apply_single(self, data, meta):
        data = data / 255.0
        out, params = self.normalize(data, cval=np.amax(data).item())
        meta['center'] = params
        return (out * 255).astype('uint8')

    def set_height(self, target_height):
        self.target_height = target_height

    def measure(self, line):
        h, w = line.shape
        smoothed = cv.GaussianBlur(line, (0, 0), sigmaX=h*self.smoothness, sigmaY=h*.5,
                                   borderType=cv.BORDER_CONSTANT)
        smoothed += .001 * cv.blur(smoothed, (w, int(h*.5)))

        a = np.argmax(smoothed, axis=0)
        kernel = cv.getGaussianKernel(int((8.*h*self.extra)+.5)+1, h*self.extra)
        center = cv.filter2D(a, cv.CV_8U, kernel, borderType=cv.BORDER_REFLECT).flatten()
        deltas = abs(np.arange(h)[:, np.newaxis] - center[np.newaxis, :])
        mad = np.mean(deltas[line != 0])
        r = int(1 + self.range * mad)
        return center, r

    def dewarp(self, img, cval=0, dtype=np.dtype('f')):
        temp = np.amax(img) - img
        amax = np.amax(temp)
        if amax == 0:
            # white image
            return temp

        temp = temp * 1.0 / np.amax(temp)
        center, r = self.measure(temp)
        h, w = img.shape
        # The actual image img is embedded into a larger image by
        # adding vertical space on top and at the bottom (padding)
        hpadding = r  # this is large enough
        padded = np.vstack([cval * np.ones((hpadding, w)), img, cval * np.ones((hpadding, w))])
        center = center + hpadding
        dewarped = [padded[center[i] - r:center[i]+r, i] for i in range(w)]
        dewarped = np.array(dewarped, dtype=dtype).T

        return dewarped

    def scale_to_h(self, img, target_height):
        h, w = img.shape
        if h == target_height:
            return img

        scale = target_height * 1.0 / h
        target_width = np.maximum(round(scale * w), 1)
        if scale <= 1:
            # Downsampling: interpolation "area"
            out = cv.resize((img * 255.0).astype(np.uint8), (target_width, target_height),
                            interpolation=cv.INTER_AREA)
            return out / 255.0

        else:
            # Upsampling: linear interpolation
            return cv.resize(img * 1.0, (target_width, target_height), interpolation=cv.INTER_LINEAR)

    def normalize(self, img, order=1, dtype=np.dtype('f'), cval=0):
        # resize the image to a appropriate height close to the target height to speed up dewarping
        intermediate_height = int(self.target_height * 1.5)
        m1 = 1
        if intermediate_height < img.shape[0]:
            m1 = intermediate_height / img.shape[0]
            img = self.scale_to_h(img, intermediate_height)
        dewarped = self.dewarp(img.astype(dtype), cval=cval, dtype=dtype)
        t = dewarped.shape[0] - img.shape[0]

        # scale to target height
        scaled = self.scale_to_h(dewarped, self.target_height)

        m2 = scaled.shape[1] / dewarped.shape[1]
        return scaled.astype(dtype), (m1, m2, t)

    def local_to_global_pos(self, x, params):
        m1, m2, t = params['center']
        return x / m1 / m2
