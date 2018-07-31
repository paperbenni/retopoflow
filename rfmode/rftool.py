'''
Copyright (C) 2017 Taylor University, CG Cookie

Created by Dr. Jon Denning and Spring 2015 COS 424 class

Some code copied from CG Cookie Retopoflow project
https://github.com/CGCookie/retopoflow

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import sys
import math
import os
import time

import bpy
import bgl
from bpy.types import Operator
from bpy.types import SpaceView3D
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Euler

from .rfwidget import RFWidget_Default

from ..common.metaclasses import SingletonRegisterClass
from ..common.ui import Drawing
from ..options import options


class RFTool(metaclass=SingletonRegisterClass):
    action_tool = []

    preferred_tool_order = [
        # use the reported name
        # note: any tool not listed here will append to the bottom in alphabetical-sorted order
        'Contours',
        'PolyStrips',
        'PolyPen',
        'Strokes',
        'Patches',
        'Loops',
        'Relax',
        'Tweak',
    ]
    order = None

    experimental_tools = []

    @staticmethod
    def init_tools(rfcontext):
        RFTool.rfcontext = rfcontext
        RFTool.drawing = Drawing.get_instance()
        RFTool.rfwidget = rfcontext.rfwidget
        toolset = { rftool:rftool() for rftool in RFTool }  # create instances of each tool

    @staticmethod
    def get_tools():
        return RFTool.order

    @staticmethod
    def dirty_when_done(fn):
        def wrapper(*args, **kwargs):
            ret = fn(*args, **kwargs)
            RFTool.rfcontext.dirty()
            return ret
        return wrapper

    @staticmethod
    def action_call(action):
        def decorator(tool):
            RFTool.action_tool.append((action, tool))
            return tool
        return decorator

    @staticmethod
    def is_experimental(tool):
        RFTool.experimental_tools.append(tool)
        return tool

    ''' a base class for all RetopoFlow Tools '''
    def __init__(self):
        self.FSM = {}
        self._success = False
        try:
            self.init()
            self.FSM['main'] = self.modal_main
            self.FSM['selection painting'] = self.modal_selection_painting
            self.selection_painting_opts = None
            self.mode = 'main'
            self._success = True
        except Exception as e:
            print('ERROR: caught exception ' + str(e))

    def modal(self):
        try:
            if not self._success: return
            nmode = self.FSM[self.mode]()
            if nmode: self.mode = nmode
        except Exception as e:
            self.mode = 'main'
            raise e     # passing on the exception to RFContext

    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self): pass

    ''' Called when the tool is being switched into. Returns initial state '''
    def start(self):
        if not self._success: return
        self.rfwidget.set_widget('default')
        self.mode = 'main'
        return None

    ''' Called when the tool is switched away from. '''
    def end(self): pass

    def update_tool_options(self):
        if not options['tools autocollapse']: return
        for k in options.keys():
            if not k.startswith('tool ') or not k.endswith(' collapsed'): continue
            t = k.split(' ')[1]
            options[k] = (t != self.name().lower())

    ''' Called when user undoes action. Prevents bad state of tool is in non-main mode '''
    def undone(self):
        self.mode = 'main'

    def update(self): pass

    def modal_main(self): pass

    def setup_selection_painting(self, bmelem, select=None, deselect_all=False, fn_filter_bmelem=None, kwargs_select=None, kwargs_deselect=None, **kwargs):
        accel_nearest2D = {
            'vert': self.rfcontext.accel_nearest2D_vert,
            'edge': self.rfcontext.accel_nearest2D_edge,
            'face': self.rfcontext.accel_nearest2D_face,
        }[bmelem]

        if not fn_filter_bmelem:
            fn_filter_bmelem = lambda bmelem: True

        def get_bmelem(use_filter=True):
            nonlocal accel_nearest2D, fn_filter_bmelem
            bmelem, dist = accel_nearest2D(max_dist=options['select dist'])
            if not use_filter or not bmelem: return bmelem
            return bmelem if fn_filter_bmelem(bmelem) else None

        if select == None:
            # look at what's under the mouse and check if select add is used
            bmelem = get_bmelem(use_filter=False)
            adding = self.rfcontext.actions.using('select add')
            if not bmelem: return               # nothing there; leave!
            if not bmelem.select: select = True # bmelem is not selected, so we are selecting
            else: select = not adding           # bmelem is selected, so we are deselecting if "select add"
            deselect_all = not adding           # deselect all if not "select add"
        else:
            bmelem = None

        if select and kwargs_select:
            kwargs.update(kwargs_select)
        if not select and kwargs_deselect:
            kwargs.update(kwargs_deselect)

        self.selection_painting_opts = {
            'select': select,
            'get': get_bmelem,
            'kwargs': kwargs,
        }

        self.rfcontext.undo_push('select' if select else 'deselect')
        if deselect_all: self.rfcontext.deselect_all()
        if bmelem: self.rfcontext.select(bmelem, only=False, **kwargs)

        return 'selection painting'

    def modal_selection_painting(self):
        assert self.selection_painting_opts
        if not self.rfcontext.actions.using(['select','select add']):
            self.selection_painting_opts = None
            return 'main'
        bmelem = self.selection_painting_opts['get']()
        if not bmelem or bmelem.select == self.selection_painting_opts['select']:
            return
        if self.selection_painting_opts['select']:
            self.rfcontext.select(bmelem, only=False, **self.selection_painting_opts['kwargs'])
        else:
            self.rfcontext.deselect(bmelem, **self.selection_painting_opts['kwargs'])

    def draw_postview(self): pass
    def draw_postpixel(self): pass

    def name(self): return 'Unnamed RFTool'
    def icon(self): return None
    def description(self): return ''
    def helptext(self): return 'No help text given'
    def get_ui_icon(self): return None
    def get_ui_options(self): return None
    def get_tooltip(self): return None
    def get_label(self): return 'Unlabeled RFTool'

