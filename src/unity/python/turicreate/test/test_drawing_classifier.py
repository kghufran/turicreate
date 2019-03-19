# -*- coding: utf-8 -*-
# Copyright © 2019 Apple Inc. All rights reserved.
#
# Use of this source code is governed by a BSD-3-clause license that can
# be found in the LICENSE.txt file or at https://opensource.org/licenses/BSD-3-Clause

from __future__ import print_function as _
from __future__ import division as _
from __future__ import absolute_import as _
import os as _os
import turicreate as _tc
from turicreate.toolkits._main import ToolkitError as _ToolkitError
import numpy as _np
from tempfile import mkstemp as _mkstemp
import coremltools as _coremltools
from copy import copy as _copy
import sys as _sys
from . import util as test_util
import unittest
import pytest

def _build_bitmap_data():
    '''
    Build an SFrame from 10 saved drawings.
    '''
    from os.path import join as _join, realpath as _realpath
    from os.path import splitext as _splitext, basename as _basename
    from os.path import dirname as _dirname
    drawings_dir = _join(_dirname(_realpath(__file__)), "drawings")
    sf = _tc.image_analysis.load_images(drawings_dir, with_path=True)
    sf = sf.rename({"image": "drawing", "path": "label"})
    sf["label"] = sf["label"].apply(
        lambda filepath: _splitext(_basename(filepath))[0][:-1]
        # Extract the class name from the filename, "check1.png" -> "check"
        # [:-1] is to get "check" out of "check1"
        )
    return sf

def _build_stroke_data():
    '''
    Build an SFrame by generating 10 random stroke-based drawings.
    Each stroke is generated by doing a random walk on a canvas.
    '''
    num_rows_in_sframe = 10
    drawings, labels = [], []
    random = _np.random.RandomState(100)
    def _generate_random_point(point = None):
        if point is not None:
            dx = random.choice([-1, 0, 1])
            dy = random.choice([-1, 0, 1])
            next_x, next_y = point["x"] + dx, point["y"] + dy
        else:
            next_x, next_y = random.randint(1000), random.randint(1000)
        return {"x": next_x, "y": next_y}

    for label in range(num_rows_in_sframe):
        num_strokes = random.randint(10)
        drawing = []
        for stroke_id in range(num_strokes):
            drawing.append([])
            num_points = random.randint(500)
            last_point = None
            for point_id in range(num_points):
                last_point = _generate_random_point(last_point)
                drawing[-1].append(last_point)
        drawings.append(drawing)
        labels.append(label)

    return _tc.SFrame({"drawing": drawings, "label": labels})

class DrawingClassifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(self, warm_start='auto'):
        self.feature = "drawing"
        self.target = "label"
        self.check_cross_sf = _build_bitmap_data()
        self.stroke_sf = _build_stroke_data()
        self.warm_start = warm_start
        self.check_cross_model = _tc.drawing_classifier.create(
            self.check_cross_sf,
            self.target,
            feature=self.feature,
            max_iterations=10,
            warm_start=warm_start)
        self.stroke_model = _tc.drawing_classifier.create(
            self.stroke_sf,
            self.target,
            feature=self.feature,
            max_iterations=1,
            warm_start=warm_start)
        self.trains = [self.check_cross_sf, self.stroke_sf]
        self.models = [self.check_cross_model, self.stroke_model]

    def test_create_with_missing_feature(self):
        for sf in self.trains:
            with self.assertRaises(_ToolkitError):
                _tc.drawing_classifier.create(sf, self.target, 
                    feature="wrong_feature")

    def test_create_with_missing_target(self):
        for sf in self.trains:
            with self.assertRaises(_ToolkitError):
                _tc.drawing_classifier.create(sf, "wrong_target")

    def test_create_with_empty_dataset(self):
        for sf in self.trains:
            with self.assertRaises(_ToolkitError):
                _tc.drawing_classifier.create(sf[:0], self.target,
                                              feature=self.feature)

    def test_create_with_missing_coordinates_in_stroke_input(self):
        drawing = [[{"x": 1.0, "y": 1.0}], [{"x": 0.0}, {"y": 0.0}]]
        sf = _tc.SFrame({
            self.feature: [drawing], 
            self.target: ["missing_coordinates"]
            })
        with self.assertRaises(_ToolkitError):
            _tc.drawing_classifier.create(sf, self.target)

    def test_create_with_wrongly_typed_coordinates_in_stroke_input(self):
        drawing = [[{"x": 1.0, "y": 0}], [{"x": "string_x?!", "y": 0.1}]]
        sf = _tc.SFrame({
            self.feature: [drawing], 
            self.target: ["string_x_coordinate"]
            })
        with self.assertRaises(_ToolkitError):
            _tc.drawing_classifier.create(sf, self.target)

    def test_create_with_None_coordinates_in_stroke_input(self):
        drawing = [[{"x": 1.0, "y": None}], [{"x": 1.1, "y": 0.1}]]
        sf = _tc.SFrame({
            self.feature: [drawing], 
            self.target: ["none_y_coordinate"]
            })
        with self.assertRaises(_ToolkitError):
            _tc.drawing_classifier.create(sf, self.target, feature=self.feature)

    def test_create_with_empty_drawing_in_stroke_input(self):
        drawing = []
        sf = _tc.SFrame({
            self.feature: [drawing], 
            self.target: ["empty_drawing"]
            })
        # Should not error out, it should silently ignore the empty drawing
        _tc.drawing_classifier.create(sf, self.target, feature=self.feature, 
            max_iterations=1)

    def test_create_with_empty_stroke_in_stroke_input(self):
        drawing = [[{"x": 1.0, "y": 0.0}], [], [{"x": 1.1, "y": 0.1}]]
        sf = _tc.SFrame({
            self.feature: [drawing], 
            self.target: ["empty_drawing"]
            })
        # Should not error out, it should silently ignore the empty stroke
        _tc.drawing_classifier.create(sf, self.target, feature=self.feature, 
            max_iterations=1)

    def test_predict_with_sframe(self):
        for index in range(len(self.models)):
            model = self.models[index]
            sf = self.trains[index]
            preds = model.predict(sf)
            assert (preds.dtype == sf[self.target].dtype)
            assert (len(preds) == len(sf))

    def test_predict_with_sarray(self):
        for index in range(len(self.models)):
            model = self.models[index]
            sf = self.trains[index]
            preds = model.predict(sf[self.feature])
            assert (preds.dtype == sf[self.target].dtype)
            assert (len(preds) == len(sf))

    def test_evaluate_without_ground_truth(self):
        for index in range(len(self.trains)):
            model = self.models[index]
            sf = self.trains[index]
            sf_without_ground_truth = sf.select_columns([self.feature])
            with self.assertRaises(_ToolkitError):
                model.evaluate(sf_without_ground_truth)

    def test_evaluate_with_ground_truth(self):
        all_metrics = ["accuracy", "auc", "precision", "recall",
                       "f1_score", "confusion_matrix", "roc_curve"]
        for index in range(len(self.models)):
            model = self.models[index]
            sf = self.trains[index]
            individual_run_results = dict()
            for metric in all_metrics:
                evaluation = model.evaluate(sf, metric=metric)
                assert (metric in evaluation)
                individual_run_results[metric] = evaluation[metric]
            evaluation = model.evaluate(sf, metric="auto")
            for metric in all_metrics:
                if metric in ["confusion_matrix", "roc_curve"]:
                    test_util.SFrameComparer()._assert_sframe_equal(
                        individual_run_results[metric], 
                        evaluation[metric])
                else:
                    assert (metric in evaluation)
                    assert (individual_run_results[metric] == evaluation[metric])

    def test_evaluate_with_unsupported_metric(self):
        for index in range(len(self.trains)):
            model = self.models[index]
            sf = self.trains[index]
            with self.assertRaises(_ToolkitError):
                model.evaluate(sf, metric="unsupported")

    def test_save_and_load(self):
        for index in range(len(self.models)):
            old_model, data = self.models[index], self.trains[index]
            with test_util.TempDirectory() as filename:
                old_model.save(filename)
                new_model = _tc.load_model(filename)
                old_preds = old_model.predict(data)
                new_preds = new_model.predict(data)
                assert (new_preds.dtype == old_preds.dtype 
                    and (new_preds == old_preds).all())

    @unittest.skipIf(_sys.platform == "darwin", "test_export_coreml_with_predict(...) covers this functionality and more")
    def test_export_coreml(self):
        for model in self.models:
            filename = _mkstemp("bingo.mlmodel")[1]
            model.export_coreml(filename)

    @unittest.skipIf(_sys.platform != "darwin", "Core ML only supported on Mac")
    def test_export_coreml_with_predict(self):
        for test_number in range(len(self.models)):
            feature = self.feature
            model = self.models[test_number]
            sf = self.trains[test_number]
            if self.warm_start:
                prefix = "pretrained" + str(test_number)
            else:
                prefix = "scratch" + str(test_number)
            filename = _mkstemp(prefix + ".mlmodel")[1]
            model.export_coreml(filename)
            mlmodel = _coremltools.models.MLModel(filename)
            tc_preds = model.predict(sf)
            if test_number == 1:
                # stroke input
                sf[feature] = _tc.drawing_classifier.util.draw_strokes(
                    sf[self.feature])

            for row_number in range(len(sf)):
                core_ml_preds = mlmodel.predict({
                    "drawing": sf[feature][row_number]._to_pil_image()
                    })
                assert (core_ml_preds["classLabel"] == tc_preds[row_number])

            if test_number == 1:
                sf = sf.remove_column(feature)

    def test_draw_strokes_sframe(self):
        sf = self.stroke_sf
        sf["rendered"] = _tc.drawing_classifier.util.draw_strokes(
            sf[self.feature])
        for index in range(len(sf["rendered"])):
            rendered = sf["rendered"][index]
            assert (type(rendered) == _tc.Image 
                and rendered.channels == 1 
                and rendered.width == 28 
                and rendered.height == 28)

    def test_draw_strokes_single_input(self):
        sf = self.stroke_sf
        single_bitmap = _tc.drawing_classifier.util.draw_strokes(
            sf[self.feature][0])
        assert (type(single_bitmap) == _tc.Image 
            and single_bitmap.channels == 1 
            and single_bitmap.width == 28 
            and single_bitmap.height == 28)

    def test_repr(self):
        for model in self.models:
            self.assertEqual(type(str(model)), str)
            self.assertEqual(type(model.__repr__()), str)

    def test_summary(self):
        for model in self.models:
            model.summary()

class DrawingClassifierFromScratchTest(DrawingClassifierTest):
    @classmethod
    def setUpClass(self):
        super(DrawingClassifierFromScratchTest, self).setUpClass(
            warm_start=None)

