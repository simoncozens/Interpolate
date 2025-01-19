import objc
from AppKit import NSBezierPath, NSColor, NSPoint
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from fontTools.varLib.models import VariationModel, normalizeValue
from GlyphsApp import (
    DRAWBACKGROUND,
    UPDATEINTERFACE,
    Glyphs,
    GSEditViewController,
)
from GlyphsApp.plugins import PalettePlugin
from vanilla import EditText, Group, Slider, TextBox, Window

KEY = "co.uk.corvelsoftware.interpolate"


class AxisSlider(Group):
    def __init__(self, axis, min_value, max_value, *args, **kwargs):
        super(AxisSlider, self).__init__("auto")
        self.axis = axis
        self.callback = kwargs["callback"]
        self.label = TextBox(
            "auto",
            axis.axisTag,
            sizeStyle="mini",
        )
        self.slider = Slider(
            "auto",
            callback=self.update_pos_from_slider,
            minValue=min_value,
            maxValue=max_value,
            value=min_value,
            continuous=True,
            sizeStyle="mini",
        )
        self.valuebox = EditText(
            "auto",
            text=str(min_value),
            sizeStyle="mini",
            callback=self.update_pos_from_text,
        )

        rules = ["H:|-[label]-[slider]-[valuebox(==40)]-|"]
        metrics = {}
        self.addAutoPosSizeRules(rules, metrics)

    def get(self):
        return self.slider.get()

    def update_pos_from_text(self, sender):
        try:
            self.slider.set(float(sender.get()))
            self.callback(self.axis, float(sender.get()))
        except Exception as e:
            print(e)

    def update_pos_from_slider(self, sender):
        self.valuebox.set(sender.get())
        self.callback(self.axis, sender.get())


class Interpolate(PalettePlugin):
    dialog = objc.IBOutlet()

    def __init__(self):
        super(Interpolate, self).__init__()
        self.current_location = {}
        self.glyph_points = {}
        self.model = None
        self.master_scalars = []

    @objc.python_method
    def settings(self):
        self.name = "Interpolate"
        width = 160
        height = 120
        self.paletteView = Window((width, height + 10))

    @objc.python_method
    def setup_axes(self):
        newframe = Group("auto")
        objects = []
        self.axis_min_max = {}
        for i, axis in enumerate(Glyphs.font.axes):
            # These should really be external, but for now
            min_value = min(
                master.internalAxesValues[i] for master in Glyphs.font.masters
            )
            max_value = max(
                master.internalAxesValues[i] for master in Glyphs.font.masters
            )
            self.axis_min_max[axis.axisTag] = (min_value, max_value)
            self.current_location[axis.axisTag] = -1.0
            axisgroup = AxisSlider(
                axis, min_value, max_value, callback=self.update_position
            )
            setattr(newframe, "axis_" + axis.axisTag, axisgroup)
            objects.append("axis_" + axis.axisTag)
        newframe.flex = Group("auto")
        rules = [
            "V:|" + "-".join(f"[{name}(==20)]" for name in objects) + "[flex]-|",
            "H:|[flex]|",
        ] + [f"H:|[{name}]|" for name in objects]

        newframe.addAutoPosSizeRules(rules)
        self.paletteView.frame = newframe

    def build_model(self):
        # Build variation model
        if hasattr(self, "model") and self.model:
            return
        layers = Glyphs.font.selectedLayers
        if not layers:
            return
        layer = layers[0]

        locations = []
        for layer in layer.parent.layers:
            if not Glyphs.font.masters[layer.layerId]:
                continue  # XXX
            master = Glyphs.font.masters[layer.associatedMasterId]
            normalized_location = {}
            for ix, axis in enumerate(Glyphs.font.axes):
                normalized_location[axis.axisTag] = normalizeValue(
                    master.internalAxesValues[ix],
                    (
                        self.axis_min_max[axis.axisTag][0],
                        self.axis_min_max[axis.axisTag][0],
                        self.axis_min_max[axis.axisTag][1],
                    ),
                )
            locations.append(normalized_location)
        # if avar_mapping is not None:
        #     locations = [
        #         {
        #             k: piecewiseLinearMap(v, avar_mapping[k]) if k in avar_mapping else v
        #             for k, v in location.items()
        #         }
        #         for location in locations
        #     ]
        self.model = VariationModel(locations)

    @objc.python_method
    def update_position(self, axis, value):
        self.current_location[axis.axisTag] = normalizeValue(
            value,
            (
                self.axis_min_max[axis.axisTag][0],
                self.axis_min_max[axis.axisTag][0],
                self.axis_min_max[axis.axisTag][1],
            ),
        )
        if hasattr(self, "model") and self.model:
            self.master_scalars = self.model.getMasterScalars(self.current_location)
        self.update_glyph()

    @objc.python_method
    def update_glyph(self):
        if not Glyphs.font.selectedLayers or not hasattr(self, "master_scalars"):
            return
        current_layer = Glyphs.font.selectedLayers[0]
        current_layer_id = current_layer.layerId
        # Rebuild the .glyph_points array as efficiently as possible
        for ix, layer in enumerate(current_layer.parent.layers):
            if not Glyphs.font.masters[layer.layerId]:
                continue  # XXX
            if ix not in self.glyph_points or layer.layerId == current_layer_id:
                self.glyph_points[ix] = []
                for path in layer.paths:
                    for seg_ix, seg in enumerate(path.segments):
                        # This does not feel efficient :-(
                        if seg_ix == 0:
                            self.glyph_points[ix].append((seg[0].x, seg[0].y))
                        self.glyph_points[ix].append((seg[1].x, seg[1].y))
                        if len(seg) == 4:
                            self.glyph_points[ix].append((seg[2].x, seg[2].y))
                            self.glyph_points[ix].append((seg[3].x, seg[3].y))

                self.glyph_points[ix] = GlyphCoordinates(self.glyph_points[ix])

        all_points = list(self.glyph_points.values())
        if any(len(points) != len(all_points[0]) for points in all_points):
            return
        print("Master scalars: ", self.master_scalars)
        print("Values: ", len(all_points))
        if len(self.master_scalars) != len(all_points):
            return
        interpolated_points = self.model.interpolateFromValuesAndScalars(
            all_points,
            self.master_scalars,
        )

        # Build a new NSBezierPath from the interpolated points
        displaypath = NSBezierPath.alloc().init()
        point_iter = iter(interpolated_points)
        for path in current_layer.paths:
            for ix, seg in enumerate(path.segments):
                if ix == 0:
                    move = NSPoint(*next(point_iter))
                    displaypath.moveToPoint_(move)
                if len(seg) == 2:
                    line = NSPoint(*next(point_iter))
                    displaypath.lineToPoint_(line)
                elif len(seg) == 3:
                    cp1 = NSPoint(*next(point_iter))
                    dest = NSPoint(*next(point_iter))
                    displaypath.curveToPoint_controlPoint_(
                        dest,
                        cp1,
                    )
                else:
                    cp1 = NSPoint(*next(point_iter))
                    cp2 = NSPoint(*next(point_iter))
                    dest = NSPoint(*next(point_iter))
                    displaypath.curveToPoint_controlPoint1_controlPoint2_(
                        dest,
                        cp1,
                        cp2,
                    )
        self.displaypath = displaypath
        Glyphs.redraw()

    @objc.python_method
    def drawBackground(self, *args):
        if hasattr(self, "displaypath") and self.displaypath:
            NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.5, 0.15).set()
            self.displaypath.fill()

    @objc.python_method
    def start(self):
        self.current_location = {}
        self.current_glyph = None
        self.glyph_points = {}  # Need to reset this when glyph changes
        self.setup_axes()  # Need to reset if axes change
        self.build_model()  # Need to reset if glyph changes
        self.dialog = self.paletteView.frame.getNSView()

        Glyphs.addCallback(self.update, UPDATEINTERFACE)
        Glyphs.addCallback(self.drawBackground, DRAWBACKGROUND)

    @objc.python_method
    def __del__(self):
        Glyphs.removeCallback(self.update)

    @objc.python_method
    def update(self, sender):
        currentTab = sender.object()
        if not isinstance(currentTab, GSEditViewController):
            return
        if not Glyphs.font.selectedLayers or len(Glyphs.font.masters) == 1:
            return
        if (
            not hasattr(self, "current_glyph")
            or Glyphs.font.selectedLayers[0].parent != self.current_glyph
        ):
            self.glyph_points = {}
            self.build_model()
            self.current_glyph = Glyphs.font.selectedLayers[0].parent
        self.update_glyph()

    @objc.python_method
    def __file__(self):
        """Please leave this method unchanged"""
        return __file__
