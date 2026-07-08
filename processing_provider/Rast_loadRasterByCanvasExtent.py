# -*- coding: utf-8 -*-

"""
Rast_loadRasterByCanvasExtent.py
Charge les rasters d'un dossier qui intersectent l'emprise du canevas.
"""

__author__ = 'zoul'
__date__ = '2026-06-29'

from qgis.core import (
    QgsProcessing,
    QgsPointXY,
    QgsGeometry,
    QgsRectangle,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFile,
    QgsApplication,
    QgsProject,
    QgsRasterLayer,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
)

from osgeo import gdal
import os
from qgis.PyQt.QtGui import QIcon


def reprojectPoints(geom, xform):
    if geom.type() == 0:  # Point
        if geom.isMultipart():
            pnts = geom.asMultiPoint()
            newPnts = [xform.transform(pnt) for pnt in pnts]
            return QgsGeometry.fromMultiPointXY(newPnts)
        else:
            return QgsGeometry.fromPointXY(xform.transform(geom.asPoint()))

    elif geom.type() == 1:  # Ligne
        if geom.isMultipart():
            linhas = geom.asMultiPolyline()
            newLines = [[xform.transform(pnt) for pnt in linha] for linha in linhas]
            return QgsGeometry.fromMultiPolylineXY(newLines)
        else:
            newLine = [xform.transform(pnt) for pnt in geom.asPolyline()]
            return QgsGeometry.fromPolylineXY(newLine)

    elif geom.type() == 2:  # Polygone
        if geom.isMultipart():
            poligonos = geom.asMultiPolygon()
            newPolygons = [
                [[xform.transform(pnt) for pnt in anel] for anel in pol]
                for pol in poligonos
            ]
            return QgsGeometry.fromMultiPolygonXY(newPolygons)
        else:
            pol = geom.asPolygon()
            newPol = [[xform.transform(pnt) for pnt in anel] for anel in pol]
            return QgsGeometry.fromPolygonXY(newPol)

    return None


class LoadRasterByCanvasExtent(QgsProcessingAlgorithm):

    FOLDER = 'FOLDER'
    SUBFOLDER = 'SUBFOLDER'
    FORMAT = 'FORMAT'
    EXTENT = 'EXTENT'

    def createInstance(self):
        return LoadRasterByCanvasExtent()

    def name(self):
        return 'loadrasterbycanvasextent'

    def displayName(self):
        return 'Charger les rasters par emprise du canevas'

    def group(self):
        return 'Raster'

    def groupId(self):
        return 'raster'

    def tags(self):
        return 'raster,charger,emprise,canevas,localisation,intersection'.split(',')

    def shortHelpString(self):
        return (
            'Charge les fichiers raster d\'un dossier (et optionnellement ses '
            'sous-dossiers) qui intersectent l\'emprise spécifiée.\n\n'
            'Paramétrez l\'emprise sur celle du canevas via le bouton dédié '
            'du paramètre Emprise.'
        )

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterFile(
                self.FOLDER,
                'Dossier contenant les fichiers raster',
                behavior=QgsProcessingParameterFile.Folder,
                defaultValue=None,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SUBFOLDER,
                'Inclure les sous-dossiers',
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.FORMAT,
                'Extension des fichiers raster',
                defaultValue='.tif',
            )
        )

        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT,
                'Emprise (utilisez l\'emprise du canevas)',
                optional=False,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):

        pasta = self.parameterAsFile(parameters, self.FOLDER, context)
        if not pasta:
            raise QgsProcessingException('Dossier source invalide.')

        subpasta = self.parameterAsBool(parameters, self.SUBFOLDER, context)
        formato = self.parameterAsString(parameters, self.FORMAT, context)

        # Récupération de l'emprise et de son CRS
        extent = self.parameterAsExtent(parameters, self.EXTENT, context)
        extent_crs = self.parameterAsExtentCrs(parameters, self.EXTENT, context)

        # Construction du polygone de l'emprise
        canvas_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(extent.xMinimum(), extent.yMaximum()),
            QgsPointXY(extent.xMaximum(), extent.yMaximum()),
            QgsPointXY(extent.xMaximum(), extent.yMinimum()),
            QgsPointXY(extent.xMinimum(), extent.yMinimum()),
            QgsPointXY(extent.xMinimum(), extent.yMaximum()),
        ]])

        # Listage des fichiers
        feedback.pushInfo('Recherche des fichiers raster dans le dossier...')
        lista = []
        if subpasta:
            for root, dirs, files in os.walk(pasta, topdown=True):
                for name in files:
                    if name.endswith(formato):
                        lista.append(os.path.join(root, name))
        else:
            for item in os.listdir(pasta):
                if item.endswith(formato):
                    lista.append(os.path.join(pasta, item))

        if not lista:
            feedback.pushInfo('Aucun fichier raster trouvé avec l\'extension "{}".'.format(formato))
            return {'fichiers': []}

        feedback.pushInfo('{} fichier(s) trouvé(s). Vérification des intersections...'.format(len(lista)))
        total = 100.0 / len(lista)
        selecao = []

        for current, file_path in enumerate(lista):
            if feedback.isCanceled():
                break

            try:
                image = gdal.Open(file_path)
                if image is None:
                    feedback.pushInfo('Impossible d\'ouvrir : {}'.format(file_path))
                    continue

                prj = image.GetProjection()
                ulx, xres, xskew, uly, yskew, yres = image.GetGeoTransform()
                cols = image.RasterXSize
                rows = image.RasterYSize
                image = None  # Fermeture

                # BBox du raster
                raster_geom = QgsGeometry.fromPolygonXY([[
                    QgsPointXY(ulx, uly),
                    QgsPointXY(ulx + cols * xres, uly),
                    QgsPointXY(ulx + cols * xres, uly + rows * yres),
                    QgsPointXY(ulx, uly + rows * yres),
                    QgsPointXY(ulx, uly),
                ]])

                # Reprojection du raster vers le CRS de l'emprise
                raster_crs = QgsCoordinateReferenceSystem(prj)
                xform = QgsCoordinateTransform()
                xform.setSourceCrs(raster_crs)
                xform.setDestinationCrs(extent_crs)
                raster_geom_reproj = reprojectPoints(raster_geom, xform)

                if raster_geom_reproj and raster_geom_reproj.intersects(canvas_geom):
                    selecao.append(file_path)
                    feedback.pushInfo('✔ Sélectionné : {}'.format(os.path.basename(file_path)))

            except Exception as e:
                feedback.pushInfo('Erreur sur {} : {}'.format(file_path, str(e)))

            feedback.setProgress(int((current + 1) * total))

        feedback.pushInfo('{} raster(s) sélectionné(s).'.format(len(selecao)))
        feedback.pushInfo('Opération terminée avec succès !')

        self.LISTA = selecao
        self.FORMATO = formato
        return {'fichiers': self.LISTA}

    def postProcessAlgorithm(self, context, feedback):
        for file_path in self.LISTA:
            layer_name = os.path.basename(file_path)[: -len(self.FORMATO)]
            rlayer = QgsRasterLayer(file_path, layer_name)
            QgsProject.instance().addMapLayer(rlayer)
        return {}

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'ZoulPixArt20.png'))