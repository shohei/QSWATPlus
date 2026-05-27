# -*- coding: utf-8 -*-
"""
/***************************************************************************
 QSWATPlus
                                 A QGIS plugin
 Create SWATPlus inputs
                              -------------------
        begin                : 2014-07-18
        copyright            : (C) 2014 by Chris George
        email                : cgeorge@mcmaster.ca
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
# Import the PyQt and QGIS libraries
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import QTextEdit
from qgis.core import QgsProject, QgsVectorLayer
import math
import os
import os.path
import subprocess
import time
import webbrowser
from typing import Optional, List, Tuple
import numpy as np
from osgeo import gdal

from .QSWATUtils import QSWATUtils  # type: ignore
from .parameters import Parameters  # type: ignore

class TauDEMUtils:
    
    """Methods for calling TauDEM executables."""
    
    @staticmethod
    def runPitFill(demFile: str, depmask: Optional[str], felFile: str, numProcesses: int, output: Optional[QTextEdit]) -> bool:
        """Run PitFill."""
        inFiles = [('-z', demFile)]
        if depmask is not None:
            inFiles.append(('-depmask', depmask))
        return TauDEMUtils.run('pitremove', inFiles, [], [('-fel', felFile)], numProcesses, output, False)

    @staticmethod
    def agreeFlatConditioning(felFile: str, streamFile: str, epsilon: float = 1.0) -> None:
        """Condition flat cells in pitfilled DEM to route toward the reference stream network.

        TauDEM's flat-cell resolution iterates in platform-dependent order, producing different
        D8 flow directions on ARM64 vs x86_64.  This function applies an AGREE-style gradient
        to flat cells (cells with no strictly lower neighbour): flat cells closer to the
        reference stream network are lowered by more (up to epsilon metres), guiding D8 routing
        toward the channels regardless of platform.  The file is rewritten as Float32.
        """
        if not os.path.exists(felFile):
            return
        ds = gdal.Open(felFile, gdal.GA_ReadOnly)
        if ds is None:
            return
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        nCols = ds.RasterXSize
        nRows = ds.RasterYSize
        geotransform = ds.GetGeoTransform()
        projection = ds.GetProjection()
        data = band.ReadAsArray().astype(np.float32)
        ds = None

        valid = np.ones((nRows, nCols), dtype=bool)
        if nodata is not None:
            valid = ~np.isclose(data, np.float32(nodata))

        # Rasterize stream lines onto the felFile grid using Bresenham's algorithm
        stream_mask = np.zeros((nRows, nCols), dtype=bool)
        ox, px, _, oy, _, py = geotransform  # ox=origin_x, px=pixel_w, oy=origin_y, py=pixel_h (negative)
        streamLayer = QgsVectorLayer(streamFile, 'AGREE', 'ogr')
        for reach in streamLayer.getFeatures():
            geom = reach.geometry()
            lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for line in lines:
                for i in range(len(line) - 1):
                    p0 = line[i]
                    x0 = int((p0.x() - ox) / px)
                    y0 = int((p0.y() - oy) / py)
                    p1 = line[i + 1]
                    x1 = int((p1.x() - ox) / px)
                    y1 = int((p1.y() - oy) / py)
                    steep = abs(y1 - y0) > abs(x1 - x0)
                    if steep:
                        x0, y0 = y0, x0
                        x1, y1 = y1, x1
                    if x0 > x1:
                        x0, x1 = x1, x0
                        y0, y1 = y1, y0
                    dx, dy = x1 - x0, abs(y1 - y0)
                    err, y, ystep = 0, y0, (1 if y0 < y1 else -1)
                    for x in range(x0, x1 + 1):
                        if steep:
                            if 0 <= x < nRows and 0 <= y < nCols:
                                stream_mask[x, y] = True
                        else:
                            if 0 <= x < nCols and 0 <= y < nRows:
                                stream_mask[y, x] = True
                        err += dy
                        if 2 * err >= dx:
                            y += ystep
                            err -= dx

        stream_init = stream_mask & valid
        if not np.any(stream_init):
            QSWATUtils.loginfo('agreeFlatConditioning: no stream cells found in {0}'.format(streamFile))
            return

        # Find flat cells: valid cells with no strictly lower valid neighbour
        padded = np.pad(data, 1, constant_values=np.finfo(np.float32).max)
        min_nbr = np.minimum.reduce([
            padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:],
            padded[1:-1, :-2],                    padded[1:-1, 2:],
            padded[2:,   :-2], padded[2:,  1:-1], padded[2:,  2:]
        ])
        is_flat = valid & ~stream_init & (min_nbr >= data)
        flat_count = int(np.sum(is_flat))
        if flat_count == 0:
            return

        # BFS distance from stream cells using numpy ring expansion (no scipy needed)
        dist = np.full((nRows, nCols), -1, dtype=np.int32)
        dist[stream_init] = 0
        frontier = stream_init.copy()
        step = 0
        while np.any(frontier):
            step += 1
            expanded = np.zeros((nRows, nCols), dtype=bool)
            expanded[:-1, :] |= frontier[1:, :]
            expanded[1:, :] |= frontier[:-1, :]
            expanded[:, :-1] |= frontier[:, 1:]
            expanded[:, 1:] |= frontier[:, :-1]
            expanded[:-1, :-1] |= frontier[1:, 1:]
            expanded[:-1, 1:] |= frontier[1:, :-1]
            expanded[1:, :-1] |= frontier[:-1, 1:]
            expanded[1:, 1:] |= frontier[:-1, :-1]
            new_cells = expanded & valid & (dist < 0)
            if not np.any(new_cells):
                break
            dist[new_cells] = step
            frontier = new_cells
            # Early exit once all flat cells have been reached
            if not np.any(is_flat & (dist < 0)):
                break

        # Cells still at dist=-1 are unreachable from the stream network; skip them
        reachable_flat = is_flat & (dist > 0)
        if not np.any(reachable_flat):
            QSWATUtils.loginfo('agreeFlatConditioning: no reachable flat cells near streams')
            return

        max_dist = int(dist[reachable_flat].max())
        if max_dist == 0:
            return

        # Lower flat cells by (1 - dist/max_dist) * epsilon: cells nearest stream are lowered most
        norm_dist = np.minimum(dist.astype(np.float32) / max_dist, 1.0)
        gradient = ((1.0 - norm_dist) * epsilon).astype(np.float32)
        data[reachable_flat] -= gradient[reachable_flat]

        # Recreate felFile as Float32 so sub-metre gradient values survive storage
        driver = gdal.GetDriverByName('GTiff')
        tmp = felFile + '.agree.tif'
        out_ds = driver.Create(tmp, nCols, nRows, 1, gdal.GDT_Float32)
        if out_ds is None:
            QSWATUtils.loginfo('agreeFlatConditioning: could not create temp file')
            return
        out_ds.SetGeoTransform(geotransform)
        out_ds.SetProjection(projection)
        out_band = out_ds.GetRasterBand(1)
        if nodata is not None:
            out_band.SetNoDataValue(nodata)
        out_band.WriteArray(data)
        out_ds.FlushCache()
        out_ds = None
        os.replace(tmp, felFile)
        QSWATUtils.loginfo('agreeFlatConditioning: conditioned {0} flat cells (max dist {1}) in {2}'.format(
            int(np.sum(reachable_flat)), max_dist, felFile))

    @staticmethod
    def conditionFlatStreamCells(felFile: str, streamFile: str, isBatch: bool) -> None:
        """Add a tiny stream-direction gradient to flat channel cells in the pit-filled DEM.

        pitremove fills depressions in the burned channel to a uniform 'spill elevation',
        creating flat patches on the channel.  TauDEM's flat-cell resolution resolves these
        with platform-dependent iteration order (ARM64 vs x86_64 diverge).

        This function applies a sub-centimetre gradient only to flat cells that lie on the
        reference stream: cells at the downstream end of each flat patch are lowered slightly
        more than cells at the upstream end, giving TauDEM a clear gradient to follow.
        Non-channel flat cells (plains, lakes) are left untouched so accumulation routing
        outside the reference stream is not disturbed.
        """
        from scipy.ndimage import label as ndlabel
        start = time.process_time()

        felDs = gdal.Open(felFile, gdal.GA_Update)
        if felDs is None:
            QSWATUtils.loginfo('conditionFlatStreamCells: cannot open {0}'.format(felFile))
            return
        felBand = felDs.GetRasterBand(1)
        felNodata = felBand.GetNoDataValue()
        projection = felDs.GetProjection()
        geotransform = felDs.GetGeoTransform()
        nRows = felDs.RasterYSize
        nCols = felDs.RasterXSize
        ox, px, _, oy, _, py = geotransform
        fel = felBand.ReadAsArray().astype(np.float64)

        nodata_mask = np.zeros((nRows, nCols), dtype=bool)
        if felNodata is not None:
            nodata_mask = (np.abs(fel - float(felNodata)) < 1.0)

        # Flat cells: those where the 3x3 neighbourhood has identical min and max
        padded = np.pad(fel, 1, constant_values=np.finfo(np.float64).max)
        min_nbr = np.minimum.reduce([
            padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:],
            padded[1:-1, :-2],                    padded[1:-1, 2:],
            padded[2:,   :-2], padded[2:,  1:-1], padded[2:,  2:]
        ])
        padded_max = np.pad(fel, 1, constant_values=-np.finfo(np.float64).max)
        max_nbr = np.maximum.reduce([
            padded_max[:-2, :-2], padded_max[:-2, 1:-1], padded_max[:-2, 2:],
            padded_max[1:-1, :-2],                        padded_max[1:-1, 2:],
            padded_max[2:,   :-2], padded_max[2:,  1:-1], padded_max[2:,  2:]
        ])
        flat_mask = (~nodata_mask) & (max_nbr == min_nbr)

        # Rasterize reference stream; record normalised flow-direction vector per cell
        stream_dc = np.zeros((nRows, nCols), dtype=np.float64)  # east = +
        stream_dr = np.zeros((nRows, nCols), dtype=np.float64)  # south = +
        stream_on_grid = np.zeros((nRows, nCols), dtype=bool)

        streamLayer = QgsVectorLayer(streamFile, 'FlatCond', 'ogr')
        for reach in streamLayer.getFeatures():
            geom = reach.geometry()
            lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for line in lines:
                for i in range(len(line) - 1):
                    p0, p1 = line[i], line[i + 1]
                    x0 = int((p0.x() - ox) / px)
                    y0 = int((p0.y() - oy) / py)
                    x1 = int((p1.x() - ox) / px)
                    y1 = int((p1.y() - oy) / py)
                    raw_dc = float(x1 - x0)
                    raw_dr = float(y1 - y0)
                    seg_len = math.sqrt(raw_dc ** 2 + raw_dr ** 2)
                    if seg_len < 0.5:
                        continue
                    norm_dc = raw_dc / seg_len
                    norm_dr = raw_dr / seg_len
                    steep = abs(y1 - y0) > abs(x1 - x0)
                    bx0, by0, bx1, by1 = x0, y0, x1, y1
                    if steep:
                        bx0, by0 = by0, bx0
                        bx1, by1 = by1, bx1
                    if bx0 > bx1:
                        bx0, bx1 = bx1, bx0
                        by0, by1 = by1, by0
                    dx, dy_b = bx1 - bx0, abs(by1 - by0)
                    err, by, bystep = 0, by0, (1 if by0 < by1 else -1)
                    for bx in range(bx0, bx1 + 1):
                        r, c = (bx, by) if steep else (by, bx)
                        if 0 <= r < nRows and 0 <= c < nCols:
                            stream_on_grid[r, c] = True
                            stream_dc[r, c] = norm_dc
                            stream_dr[r, c] = norm_dr
                        err += dy_b
                        if 2 * err >= dx:
                            by += bystep
                            err -= dx

        # Flat stream cells: the only cells we will modify
        flat_stream = flat_mask & stream_on_grid
        n_flat_stream = int(flat_stream.sum())
        if n_flat_stream == 0:
            felDs = None
            return

        # For each connected component of flat stream cells, apply a gradient
        # in the local stream-flow direction so TauDEM gets a clear slope.
        # Gradient magnitude: 0.001 m per cell (1 mm) — large enough for Float32,
        # small enough not to interfere with the broader topography.
        epsilon = 0.001

        labeled, n_comp = ndlabel(flat_stream)
        rows_arr, cols_arr = np.where(flat_stream)
        # Pre-build index arrays per component
        comp_ids = labeled[rows_arr, cols_arr]

        modified_count = 0
        for cid in range(1, n_comp + 1):
            sel = (comp_ids == cid)
            crows = rows_arr[sel]
            ccols = cols_arr[sel]
            # Local flow direction for this component (average of cell directions)
            dc_mean = stream_dc[crows, ccols].mean()
            dr_mean = stream_dr[crows, ccols].mean()
            norm = math.sqrt(dc_mean ** 2 + dr_mean ** 2)
            if norm < 1e-6:
                continue
            dc_mean /= norm
            dr_mean /= norm
            # Project each cell onto the flow axis: downstream = higher projection
            proj = dc_mean * ccols + dr_mean * crows  # scalar dot with position
            proj_min = proj.min()
            proj_max = proj.max()
            if proj_max <= proj_min:
                continue
            # Downstream cells (high proj) get lowered by up to epsilon
            # Upstream cells (low proj) get lowered by 0
            frac = (proj - proj_min) / (proj_max - proj_min)  # 0=upstream, 1=downstream
            lowering = frac * epsilon
            fel[crows, ccols] -= lowering
            modified_count += len(crows)

        if modified_count > 0:
            felBand.WriteArray(fel.astype(np.float32))
            felDs.FlushCache()

        felDs = None
        finish = time.process_time()
        QSWATUtils.loginfo(
            'conditionFlatStreamCells: gradient applied to {0} flat stream cells '
            '({1} components) in {2}ms'.format(
                modified_count, n_comp, int((finish - start) * 1000)))

    @staticmethod
    def runD8FlowDir(felFile: str, sd8File: str, pFile: str, numProcesses: int, output: Optional[QTextEdit]) -> bool:
        """Run D8FlowDir."""
        return TauDEMUtils.run('d8flowdir', [('-fel', felFile)], [], [('-sd8', sd8File), ('-p', pFile)],
                               numProcesses, output, False)

    @staticmethod
    def runDinfFlowDir(felFile: str, slpFile: str, angFile: str, numProcesses: int, output: Optional[QTextEdit]) -> bool:
        """Run DinfFlowDir."""
        return TauDEMUtils.run('dinfflowdir', [('-fel', felFile)], [], [('-slp', slpFile), ('-ang', angFile)], 
                               numProcesses, output, False)

    @staticmethod
    def runAreaD8(pFile: str, ad8File: str, outletFile: Optional[str], weightFile: Optional[str], 
                  numProcesses: int, output: Optional[QTextEdit], contCheck: bool=False, mustRun: bool=True) -> bool:
        """Run AreaD8."""
        inFiles = [('-p', pFile)]
        if outletFile is not None:
            inFiles.append(('-o', outletFile))
        if weightFile is not None:
            inFiles.append(('-wg', weightFile))
        check = [] if contCheck else [('-nc', '')]
        return TauDEMUtils.run('aread8', inFiles, check, [('-ad8', ad8File) ], numProcesses, output, mustRun)

    @staticmethod
    def runAreaDinf(angFile: str, scaFile: str, outletFile: Optional[str], 
                    numProcesses: int, output: Optional[QTextEdit], mustRun: bool=True) -> bool:
        """Run AreaDinf."""
        inFiles = [('-ang', angFile)]
        if outletFile is not None:
            inFiles.append(('-o', outletFile))
        return TauDEMUtils.run('areadinf', inFiles, [('-nc', '')], [('-sca', scaFile)], numProcesses, output, mustRun)

    @staticmethod
    def runGridNet(pFile: str, plenFile: str, tlenFile: str, gordFile: str, outletFile: Optional[str], 
                   numProcesses: int, output: Optional[QTextEdit], mustRun: bool=True) -> bool:
        """Run GridNet."""
        inFiles = [('-p', pFile)]
        if outletFile is not None:
            inFiles.append(('-o', outletFile))
        return TauDEMUtils.run('gridnet', inFiles, [], [('-plen', plenFile), ('-tlen', tlenFile), ('-gord', gordFile)], 
                               numProcesses, output, mustRun)
    
    @staticmethod
    def runThreshold(ad8File: str, srcFile: str, threshold: str, 
                     numProcesses: int, output: Optional[QTextEdit], mustRun: bool=True) -> bool:
        """Run Threshold."""
        return TauDEMUtils.run('threshold', [('-ssa', ad8File)], [('-thresh', threshold)], [('-src', srcFile)], 
                               numProcesses, output, mustRun)
    
    @staticmethod
    def runStreamNet(felFile: str, pFile: str, ad8File: str, srcFile: str, outletFile: Optional[str], 
                     ordFile: str, treeFile: str, coordFile: str, streamFile: str, wFile: str, 
                     single: bool, numProcesses: int, output: Optional[QTextEdit], mustRun: bool=True) -> bool:
        """Run StreamNet."""
        inFiles = [('-fel', felFile), ('-p', pFile), ('-ad8', ad8File), ('-src', srcFile)]
        if outletFile is not None:
            inFiles.append(('-o', outletFile))
        inParms = [('-sw', '')] if single else []
        return TauDEMUtils.run('streamnet', inFiles, inParms, 
                               [('-ord', ordFile), ('-tree', treeFile), ('-coord', coordFile), ('-net', streamFile), 
                                ('-w', wFile)], numProcesses, output, mustRun)
    @staticmethod
    def runMoveOutlets(pFile: str, srcFile: str, outletFile: str, movedOutletFile: str, 
                       numProcesses: int, output: Optional[QTextEdit], mustRun: bool=True) -> bool:
        """Run MoveOutlets."""
        return TauDEMUtils.run('moveoutletstostreams', [('-p', pFile), ('-src', srcFile), ('-o', outletFile)], 
                               [], [('-om', movedOutletFile)], 
                               numProcesses, output, mustRun)
        
    @staticmethod
    def runDistanceToStreams(pFile: str, hd8File: str, distFile: str, threshold: str, 
                             numProcesses: int, output: Optional[QTextEdit], mustRun: bool=True) -> bool:
        """Run D8HDistToStrm."""
        return TauDEMUtils.run('d8hdisttostrm', [('-p', pFile), ('-src', hd8File)], [('-thresh', threshold)], 
                               [('-dist', distFile)], numProcesses, output, mustRun)
    
    @staticmethod   
    def run(command: str, inFiles: List[Tuple[str, str]], inParms: List[Tuple[str, str]], 
            outFiles: List[Tuple[str, str]], numProcesses: int, output: Optional[QTextEdit], mustRun: bool) -> bool:
        """
        Run TauDEM command, using mpiexec if numProcesses is not zero.
        
        Parameters:
        inFiles: list of pairs of parameter id (string) and file path (string) 
        for input files.  May not be empty.
        inParms: list of pairs of parameter id (string) and parameter value 
        (string) for input parameters.
        For a parameter which is a flag with no value, parameter value 
        should be empty string.
        outFiles: list of pairs of parameter id (string) and file path 
        (string) for output files.
        numProcesses: number of processes to use (int).  
        Zero means do not use mpiexec.
        output: buffer for TauDEM output (QTextEdit).
        if output is None use as flag that running in batch, and errors are simply printed.
        Return: True if no error detected, else false.
        The command is not executed if 
        (1) mustRun is false (since it is set true for results that depend 
        on the threshold setting or an outlets file, which might have changed), and
        (2) all output files exist and were last modified no earlier 
        than the first input file.
        An error is detected if any input file does not exist or,
        after running the TauDEM command, 
        any output file does not exist or was last modified earlier 
        than the first input file.
        For successful output files the .prj file is copied 
        from the first input file.
        The Taudem executable directory and the mpiexec path are 
        read from QSettings.
        """
        hasQGIS = output is not None
        baseFile = inFiles[0][1]
        needToRun = mustRun
        if not needToRun:
            for (pid, fileName) in outFiles:
                if not QSWATUtils.isUpToDate(baseFile, fileName):
                    needToRun = True
                    break
        if not needToRun:
            return True
        commands: List[str] = []
        settings = QSettings()
        if hasQGIS:
            assert output is not None
            output.append('------------------- TauDEM command: -------------------\n')
        if numProcesses != 0:
            mpiexecPath = TauDEMUtils.findMPIExecPath(settings)
            if mpiexecPath != '':
                commands.append(mpiexecPath)
                commands.append('-np') # -n acceptable in Windows but only -np in OpenMPI
                commands.append(str(numProcesses))
        TauDEMDir, is539 = TauDEMUtils.findTauDEMDir(settings, hasQGIS)
        if TauDEMDir == '':
            return False
        if is539:  # which implies _ISWIN
            # pass StreamNet a directory rather than shapefile so shapefile created as a directory
            # this prevents problem that .shp cannot be deleted, but GDAL then complains that the .shp file is not a directory
            # also have to set -netlyr parameter to stop TauDEM failing to parse filename without .shp as a layer name
            # TauDEM version 5.1.2 does not support -netlyr parameter
            if command == 'streamnet':
                # make copy so can rewrite
                outFilesCopy = outFiles[:]
                outFiles = []
                for (pid, outFile) in outFilesCopy:
                    if pid == '-net':
                        streamDir = QSWATUtils.shapefileToDir(outFile)
                        outFiles.append((pid, streamDir))
                    else:
                        outFiles.append((pid, outFile))
                inParms.append(('-netlyr', os.path.split(streamDir)[1]))
        commands.append(QSWATUtils.join(TauDEMDir, command))
        for (pid, fileName) in inFiles:
            if not os.path.exists(fileName):
                TauDEMUtils.error('''File {0} for TauDEM input {1} to {2} does not exist.'''.format(fileName, pid, command), hasQGIS)
                return False
            commands.append(pid)
            commands.append(fileName)
        for (pid, parm) in inParms:
            commands.append(pid)
            # allow for parameter which is flag with no value
            if not parm == '':
                commands.append(parm)
        # remove outFiles so any error will be reported
        root = QgsProject.instance().layerTreeRoot()
        for (_, fileName) in outFiles:
            if os.path.isdir(fileName):
                QSWATUtils.tryRemoveShapefileLayerAndDir(fileName, root)
            else:
                QSWATUtils.tryRemoveLayerAndFiles(fileName, root)
        for (pid, fileName) in outFiles:
            commands.append(pid)
            commands.append(fileName)
        command = ' '.join(commands)             
        if hasQGIS:
            assert output is not None
            output.append(command + '\n\n')
            output.moveCursor(QTextCursor.MoveOperation.End)
        # Windows will accept commands as first argument of run
        # and this has the advantage of dealing with spaces within inidividual components of the list
        # Linux and MacOS need a single string (and there will be no spaces to worry about)
        # MacPrefix is needed to load gdal library from QGIS installation in case gdal not installed (or installed with different version)
        # In windows PROJ seems to need ` instead of the more recent PROJ_DATA
        # In windows gdalplugins now stored under TauDEMDir so they are compatible with gdal304 dlls stored there
        MacPrefixNeeded = Parameters._ISMAC
        MacPrefix = 'export GDAL_DATA=/opt/homebrew/share/gdal; export PROJ_LIB=/opt/homebrew/share/proj; export GDAL_PAM_ENABLED=NO; '
        procCommand = commands if Parameters._ISWIN else MacPrefix + command if MacPrefixNeeded else command
        if Parameters._ISMAC:
            QSWATUtils.loginfo(procCommand)
        if Parameters._ISWIN:
            os.environ['PROJ_LIB'] = os.getenv('PROJ_DATA')
            os.environ['GDAL_DRIVER_PATH'] = TauDEMDir + '/gdalplugins'
        proc = subprocess.run(procCommand, 
                                shell=True, 
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True)    # text=True) only in python 3.7 
        if hasQGIS:
            assert output is not None
            output.append(proc.stdout)
            output.append(proc.stderr)
            output.moveCursor(QTextCursor.MoveOperation.End)
        else:
            print(proc.stdout)
        # proc.returncode always seems to be None
        # so check TauDEM run by checking output file exists and modified later than DEM
        # not ideal as may eg generate empty file
        # TODO: improve on this
        ok = proc.returncode == 0
        msg = command + ' created '
        for (pid, fileName) in outFiles:
            if QSWATUtils.isUpToDate(baseFile, fileName):
                msg += fileName
                msg += ' '
            else:
                ok = False
        if ok:
            TauDEMUtils.loginfo(msg, hasQGIS)
        else:
            if hasQGIS:
                assert output is not None    
                origColour = output.textColor()
                output.setTextColor(Qt.GlobalColor.red)
                output.append(QSWATUtils.trans('*** Problem with TauDEM {0}: please examine output above. ***'.format(command)))
                output.setTextColor(origColour)
            msg += 'and failed'
            TauDEMUtils.logerror(msg, hasQGIS)
        return ok

    @staticmethod
    def findTauDEMDir(settings: QSettings, hasQGIS: bool) -> Tuple[str, bool]:
        """Find and return path of TauDEM directory, plus flag indicating if 539 directory used."""
        is539 = False
        SWATPlusDir = settings.value('/QSWATPlus/SWATPlusDir', Parameters._SWATPLUSDEFAULTDIR)
        TauDEMDir: str = QSWATUtils.join(SWATPlusDir, Parameters._TAUDEM539DIR) if Parameters._ISWIN else QSWATUtils.join(SWATPlusDir, Parameters._TAUDEMDIR)
        if os.path.isdir(TauDEMDir):
            is539 = Parameters._ISWIN
        else:
            if Parameters._ISWIN:
                TauDEMDir2 = QSWATUtils.join(SWATPlusDir, Parameters._TAUDEMDIR)
                if os.path.isdir(TauDEMDir2):
                    TauDEMDir = TauDEMDir2
                else:
                    TauDEMDir3 = QSWATUtils.join(r'C:\SWAT\SWATPlus', Parameters._TAUDEM539DIR)
                    if os.path.isdir(TauDEMDir3):
                        TauDEMDir = TauDEMDir3
                        is539 = True
                    else:
                        TauDEMDir4 = QSWATUtils.join(r'C:\SWAT\SWATPlus', Parameters._TAUDEMDIR)
                        if os.path.isdir(TauDEMDir4):
                            TauDEMDir = TauDEMDir4
                        else:
                            TauDEMDir5 = QSWATUtils.join(r'C:\SWAT\SWATEditor', Parameters._TAUDEM539DIR)  # path from QSWAT
                            if os.path.isdir(TauDEMDir5):
                                TauDEMDir = TauDEMDir5
                                is539 = True
                            else:
                                TauDEMDir6 = QSWATUtils.join(r'C:\SWAT\SWATEditor', Parameters._TAUDEMDIR)
                                if os.path.isdir(TauDEMDir6):
                                    TauDEMDir = TauDEMDir6
                                else:
                                    TauDEMUtils.error('''Cannot find TauDEM directory as {0}, {1}, {2}, {3}, {4} or {5}.  
            Have you installed SWAT+ as a different directory from C:/SWAT/SWATPlus?
            If so use the QSWAT+ Parameters form to set the correct location.'''.
            format(TauDEMDir, TauDEMDir2, TauDEMDir3, TauDEMDir4, TauDEMDir5, TauDEMDir6), hasQGIS)
                                    return  '', False
            else:
                TauDEMDir2 = QSWATUtils.join(Parameters._SWATPLUSDEFAULTDIR, Parameters._TAUDEMDIR)
                if os.path.isdir(TauDEMDir2):
                    TauDEMDir = TauDEMDir2
                    # should be suitable for Linux and Mac but in batch Linux fails to make the directory
                    # is539 = True
                else:
                    TauDEMUtils.error('''Cannot find TauDEM directory as {0} or {1}.  
Have you installed SWATPlus?'''.format(TauDEMDir, TauDEMDir2), hasQGIS)
                    return '', False
        QSWATUtils.loginfo('TauDEM directory is {0}'.format(TauDEMDir))
        return TauDEMDir, is539
    
    @staticmethod
    def findMPIExecPath(settings: QSettings) -> str:
        """Find and return path of MPI execuatable, if any, else None."""
        if settings.contains('/QSWATPlus/mpiexecDir'):
            path: str = QSWATUtils.join(settings.value('/QSWATPlus/mpiexecDir'), Parameters._MPIEXEC)
        else:
            settings.setValue('/QSWATPlus/mpiexecDir', Parameters._MPIEXECDEFAULTDIR)
            path = QSWATUtils.join(Parameters._MPIEXECDEFAULTDIR, Parameters._MPIEXEC)
        if os.path.exists(path):
            return path
        else:
            return ''

    @staticmethod
    def taudemHelp() -> None:
        """Display TauDEM help file."""
        settings = QSettings()
        TauDEMDir, _ = TauDEMUtils.findTauDEMDir(settings, False)
        if Parameters._ISWIN and TauDEMDir != '':
            taudemHelpFile = QSWATUtils.join(TauDEMDir, Parameters._TAUDEMHELP)
            QSWATUtils.loginfo('TauDEM help file is {0}'.format(taudemHelpFile))
            os.startfile(taudemHelpFile)  # @UndefinedVariable since not defined in Linux
        else:
            webbrowser.open(Parameters._TAUDEMDOCS)
        
    @staticmethod
    def error(msg: str, hasQGIS: bool) -> None:
        """Report error, just printing if no QGIS running."""
        if hasQGIS:
            QSWATUtils.error(msg, False)
        else:
            print(msg)
            
    @staticmethod
    def loginfo(msg: str, hasQGIS: bool) -> None:
        """Log msg, just printing if no QGIS running."""
        if hasQGIS:
            QSWATUtils.loginfo(msg)
        else:
            print(msg)
            
    @staticmethod
    def logerror(msg: str, hasQGIS: bool) -> None:
        """Log error msg, just printing if no QGIS running."""
        if hasQGIS:
            QSWATUtils.logerror(msg)
        else:
            print(msg)
        
