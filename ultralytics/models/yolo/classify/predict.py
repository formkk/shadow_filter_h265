# Ultralytics YOLO 🚀, AGPL-3.0 license

import cv2
import torch
from PIL import Image

from ultralytics.engine.predictor import BasePredictor
from ultralytics.engine.results import Results
from ultralytics.utils import DEFAULT_CFG, ops


class ClassificationPredictor(BasePredictor):
    """
    A class extending the BasePredictor class for prediction based on a classification model.

    Notes:
        - Torchvision classification models can also be passed to the 'model' argument, i.e. model='resnet18'.

    Example:
        ```python
        from ultralytics.utils import ASSETS
        from ultralytics.models.yolo.classify import ClassificationPredictor

        args = dict(model="yolov8n-cls.pt", source=ASSETS)
        predictor = ClassificationPredictor(overrides=args)
        predictor.predict_cli()
        ```
    """

    def __init__(self, cfg=DEFAULT_CFG, overrides=None, _callbacks=None):
        """Initializes ClassificationPredictor setting the task to 'classify'."""
        super().__init__(cfg, overrides, _callbacks)
        self.args.task = "classify"
        self._legacy_transform_name = "ultralytics.yolo.data.augment.ToTensor"

    def preprocess(self, img):
        """Converts input image to model-compatible data type."""
        try:
            if not isinstance(img, torch.Tensor):
                is_legacy_transform = False
                try:
                    for transform in self.transforms.transforms:
                        if hasattr(transform, '__class__') and hasattr(transform.__class__, '__module__'):
                            transform_module = transform.__class__.__module__
                            if self._legacy_transform_name in transform_module:
                                is_legacy_transform = True
                                break
                except Exception:
                    is_legacy_transform = False
                
                if is_legacy_transform:  # to handle legacy transforms
                    img = torch.stack([self.transforms(im) for im in img], dim=0)
                else:
                    img = torch.stack(
                        [self.transforms(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))) for im in img], dim=0
                    )
            img = (img if isinstance(img, torch.Tensor) else torch.from_numpy(img)).to(self.model.device)
            return img.half() if self.model.fp16 else img.float()  # uint8 to fp16/32
        except AttributeError as e:
            if 'max_size' in str(e) and hasattr(self, 'transforms') and hasattr(self.transforms, 'transforms'):
                new_transforms = []
                for transform in self.transforms.transforms:
                    if hasattr(transform, 'size') and not hasattr(transform, 'max_size'):
                        size = transform.size
                        if hasattr(transform, 'interpolation'):
                            interpolation = transform.interpolation
                            import torchvision.transforms as T
                            new_resize = T.Resize(size=size, interpolation=interpolation)
                            new_transforms.append(new_resize)
                        else:
                            new_transforms.append(transform)
                    else:
                        new_transforms.append(transform)
                self.transforms.transforms = new_transforms
                return self.preprocess(img)
            else:
                raise

    def postprocess(self, preds, img, orig_imgs):
        """Post-processes predictions to return Results objects."""
        if not isinstance(orig_imgs, list):  # input images are a torch.Tensor, not a list
            orig_imgs = ops.convert_torch2numpy_batch(orig_imgs)

        return [
            Results(orig_img, path=img_path, names=self.model.names, probs=pred)
            for pred, orig_img, img_path in zip(preds, orig_imgs, self.batch[0])
        ]
