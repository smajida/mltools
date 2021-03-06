# Extract pixels and metadata using shapefiles and georeferenced imagery.
# The purpose of this module is to generate train, test and target data
# for machine learning algorithms.

import geoio
import geojson
import geojson_tools as gt
import numpy as np
import sys
from itertools import cycle
import osgeo.gdal as gdal
from osgeo.gdalconst import *
from functools import reduce


def get_data(shapefile, return_labels=False, buffer=[0, 0], mask=False):
    """Return pixel intensity array for each geometry in shapefile.
       The image reference for each geometry is found in the image_id
       property of the shapefile.
       If shapefile contains points, then buffer must have non-zero entries.
       The function also returns a list of geometry ids; this is useful in
       case some of the shapefile entries do not produce a valid intensity
       array and/or class name.

       Args:
           shapefile (str): Name of shapefile in mltools geojson format.
           return_labels (bool): If True, then a label vector is returned.
           buffer (list): 2-dim buffer in PIXELS. The size of the box in each
                          dimension is TWICE the buffer size.
           mask (bool): Return a masked array.

       Returns:
           chips (list): List of pixel intensity numpy arrays.
           ids (list): List of corresponding geometry ids.
           labels (list): List of class names, if return_labels=True
    """

    data = []

    # go through point_file and unique image_id's
    image_ids = gt.find_unique_values(shapefile, property_name='image_id')

    # go through the shapefile for each image --- this is how geoio works
    for image_id in image_ids:

        # add tif extension
        img = geoio.GeoImage(image_id + '.tif')

        for chip, properties in img.iter_vector(vector=shapefile,
                                                properties=True,
                                                filter=[
                                                    {'image_id': image_id}],
                                                buffer=buffer,
                                                mask=mask):

            if chip is None or reduce(lambda x, y: x * y, chip.shape) == 0:
                continue

            # every geometry must have id
            this_data = [chip, properties['feature_id']]

            if return_labels:
                try:
                    label = properties['class_name']
                    if label is None:
                        continue
                except (TypeError, KeyError):
                    continue
                this_data.append(label)

            data.append(this_data)

    return zip(*data)


def get_iter_data(shapefile, batch_size=32, nb_classes=2, min_chip_hw=0, max_chip_hw=125,
                  classes=['No swimming pool', 'Swimming pool'], return_id = False,
                  buffer=[0, 0], mask=True, normalize=True, img_name=None,
                  return_labels=True):
    '''
    Generates batches of training data from shapefile.

    INPUT   shapefile (string): name of shapefile to extract polygons from
            batch_size (int): number of chips to generate each iteration
            nb_classes (int): number of classes in which to categorize itmes
            min_chip_hw (int): minimum size acceptable (in pixels) for a polygon.
                defaults to 30.
            max_chip_hw (int): maximum size acceptable (in pixels) for a polygon. Note
                that this will be the size of the height and width of input images to the
                net. defaults to 125.
            classes (list['string']): name of classes for chips. Defualts to swimming
                pool classes (['Swimming_pool', 'No_swimming_pool'])
            return_id (bool): return the geometry id with each chip. Defaults to False
            buffer (list[int]): two-dim buffer in pixels. defaults to [0,0].
            mask (bool): if True returns a masked array. defaults to True
            normalize (bool): divide all chips by max pixel intensity (normalize net
                input). Defualts to True.
            img_name (string): name of tif image to use for extracting chips. Defaults to
                None (the image name is assumed to be the image id listed in shapefile)
            return_labels (bool): Include labels in output. Defualts to True.

    OUTPUT  Returns a generator object (g). calling g.next() returns the following:
            chips: one batch of masked (if True) chips
            corresponding feature_id for chips (if return_id is True)
            corresponding chip labels (if return_labels is True)

    EXAMPLE:
        >> g = get_iter_data('shapefile.geojson', batch-size=12)
        >> x,y = g.next()
        # x is the first 12 chips (of appropriate size) from the input shapefile
        # y is a list of classifications for the chips in x
    '''

    ct, inputs, labels, ids = 0, [], [], []
    print 'Extracting image ids...'
    img_ids = gt.find_unique_values(shapefile, property_name='image_id')

    # Create numerical class names
    cls_dict = {classes[i]: i for i in xrange(len(classes))}

    for img_id in img_ids:
        if not img_name:
            img = geoio.GeoImage(img_id + '.tif')
        else:
            img = geoio.GeoImage(img_name)

        for chip, properties in img.iter_vector(vector=shapefile,
                                                properties=True,
                                                filter=[{'image_id': img_id}],
                                                buffer=buffer,
                                                mask=mask):

            # check for adequate chip size
            chan, h, w = np.shape(chip)
            pad_h, pad_w = max_chip_hw - h, max_chip_hw - w
            if chip is None or min(h, w) < min_chip_hw or max(
                    h, w) > max_chip_hw:
                continue

            # zero-pad chip to standard net input size
            chip = chip.filled(0).astype(float)  # replace masked entries with zeros
            chip_patch = np.pad(chip, [(0, 0), (pad_h/2, (pad_h - pad_h/2)), (pad_w/2,
                (pad_w - pad_w/2))], 'constant', constant_values=0)

            # # resize image
            # if resize_dim:
            #     if resize_dim != chip_patch.shape:
            #         chip_patch = resize(chip_patch, resize_dim)

            if normalize:
                chip_patch /= 255.

            # Get labels
            if return_labels:
                try:
                    label = properties['class_name']
                    if label is None:
                        continue
                    labels.append(cls_dict[label])
                except (TypeError, KeyError):
                    continue

            if return_id:
                id = properties['feature_id']
                ids.append(id)

            # do not include image_id for fitting net
            inputs.append(chip_patch)
            ct += 1
            sys.stdout.write('\r%{0:.2f}'.format(100 * ct / float(batch_size)) + ' ' * 5)
            sys.stdout.flush()

            if ct == batch_size:
                data = [np.array([i for i in inputs])]

                if return_id:
                    data.append(ids)

                if return_labels:
                    # Create one-hot encoded labels
                    Y = np.zeros((batch_size, nb_classes))
                    for i in range(batch_size):
                        Y[i, labels[i]] = 1

                    data.append(Y)
                yield data
                ct, inputs, labels, ids = 0, [], [], []

    # return any remaining inputs
    if len(inputs) != 0:
        data = [np.array([i for i in inputs])]

        if return_id:
            data.append(ids)

        if return_labels:
            # Create one-hot encoded labels
            Y = np.zeros((len(labels), nb_classes))
            for i in range(len(labels)):
                Y[i, labels[i]] = 1
            data.append(Y)
        yield data


def random_window(image, chip_size, no_chips=10000):
    """Implement a random chipper on a georeferenced image.

       Args:
           image (str): Image filename.
           chip_size (list): Array of chip dimensions.
           no_chips (int): Number of chips.

       Returns:
           List of chip rasters.
    """
    img = geoio.GeoImage(image)

    chips = []
    for i, chip in enumerate(img.iter_window_random(
            win_size=chip_size, no_chips=no_chips)):
        chips.append(chip)
        if i == no_chips - 1:
            break

    return chips


def apply_mask(input_file, mask_file, output_file):
    """Apply binary mask on image. Input image and mask must have the same
       (x,y) dimension and the same projection.

       Args:
           input_file (str): Input file name.
           mask_file (str): Mask file name.
           output_file (str): Masked image file name.
    """

    source_ds = gdal.Open(input_file, GA_ReadOnly)
    nbands = source_ds.RasterCount
    mask_ds = gdal.Open(mask_file, GA_ReadOnly)

    xsize, ysize = source_ds.RasterXSize, source_ds.RasterYSize
    xmasksize, ymasksize = mask_ds.RasterXSize, mask_ds.RasterYSize

    print 'Generating mask'

    # Create target DS
    driver = gdal.GetDriverByName('GTiff')
    dst_ds = driver.Create(output_file, xsize, ysize, nbands, GDT_Byte)
    dst_ds.SetGeoTransform(source_ds.GetGeoTransform())
    dst_ds.SetProjection(source_ds.GetProjection())

    # Apply mask --- this is line by line at the moment, not so efficient
    for i in range(ysize):
        # read line from input image
        line = source_ds.ReadAsArray(xoff=0, yoff=i, xsize=xsize, ysize=1)
        # read line from mask
        mask_line = mask_ds.ReadAsArray(xoff=0, yoff=i, xsize=xsize, ysize=1)
        # apply mask
        masked_line = line * (mask_line > 0)
        # write
        for n in range(1, nbands + 1):
            dst_ds.GetRasterBand(n).WriteArray(masked_line[n - 1].astype(np.uint8),
                                               xoff=0, yoff=i)
    # close datasets
    source_ds, dst_ds = None, None


class getIterData(object):
    '''
    A class for iteratively extracting chips from a geojson shapefile and one or more
        corresponding GeoTiff strips.

    INPUT   shapefile (string): name of shapefile to extract polygons from
            batch_size (int): number of chips to generate per call of self.create_batch(). Defaults to 10000
            classes (list['string']): name of classes for chips. Defualts to swimming
                pool classes (['Swimming_pool', 'No_swimming_pool'])
            min_chip_hw (int): minimum size acceptable (in pixels) for a polygon.
                defaults to 30.
            max_chip_hw (int): maximum size acceptable (in pixels) for a polygon. Note
                that this will be the size of the height and width of input images to the
                net. defaults to 125.
            return_labels (bool): Include labels in output. Defualts to True.
            return_id (bool): return the geometry id with each chip. Defaults to False
            mask (bool): if True returns a masked array. defaults to True
            normalize (bool): divide all chips by max pixel intensity (normalize net
                input). Defualts to True.
            props (dict): Proportion of chips to extract from each image strip. If the
                proportions don't add to one they will each be divided by the total of
                the values. Defaults to None, in which case proportions will be
                representative of ratios in the shapefile.

    OUTPUT  creates a class instance that will produce batches of chips from the input
                shapefile when create_batch() is called.

    EXAMPLE
            $ data_generator = getIterData('shapefile.geojson', batch_size=1000)
            $ x, y = data_generator.create_batch()
            # x = batch of 1000 chips from all image strips
            # y = labels associated with x
    '''

    def __init__(self, shapefile, batch_size=10000, min_chip_hw=0, max_chip_hw=125,
                 classes=['No swimming pool', 'Swimming pool'], return_labels=True,
                 return_id=False, mask=True, normalize=True, props=None):

        self.shapefile = shapefile
        self.batch_size = batch_size
        self.classes = classes
        self.min_chip_hw = min_chip_hw
        self.max_chip_hw = max_chip_hw
        self.return_labels = return_labels
        self.return_id = return_id
        self.mask = mask
        self.normalize = normalize

        # get image proportions
        print 'Getting image proportions...'
        if props:
            self.img_ids = props.keys()
            self.props = self._format_props_input(props)

        else:
            self.img_ids = gt.find_unique_values(shapefile, property_name='image_id')
            self.props = {}
            for id in self.img_ids:
                if int(self.get_proportion('image_id', id) * self.batch_size) > 0:
                    self.props[id] = int(self.get_proportion('image_id', id) * self.batch_size)

        # account for difference in batch size and total due to rounding
        total = np.sum(self.props.values())
        if total < batch_size:
            diff = np.random.choice(self.props.keys())
            self.props[diff] += batch_size - total

        # initialize generators
        print 'Creating chip generators for each image...'
        self.chip_gens = {}
        for id in self.img_ids:
            self.chip_gens[id] = self.yield_from_img_id(id, batch=self.props[id])

    def _format_props_input(self, props):
        '''
        helper function to format the props dict input
        '''
        # make sure proportions add to one
        total_prop = np.sum(props.values())
        for i in props.keys():
            props[i] /= float(total_prop)

        p_new = {i: int(props[i] * self.batch_size) for i in props.keys()}
        return p_new

    def get_proportion(self, property_name, property):
        '''
        Helper function to get the proportion of polygons with a given property in a
            shapefile

        INPUT   shapefile (string): name of the shapefile containing the polygons
                property_name (string): name of the property to search for exactly as it
                    appears in the shapefile properties (ex: image_id)
                property (string): the property of which to get the proportion of in the
                    shapefile (ex: '1040010014800C00')
        OUTPUT  proportion (float): proportion of polygons that have the property of interest
        '''
        total, prop = 0,0

        # open shapefile, get polygons
        with open(self.shapefile) as f:
            data = geojson.load(f)['features']

        # loop through features, find property count
        for polygon in data:
            total += 1

            try:
                if str(polygon['properties'][property_name]) == property:
                    prop += 1
            except:
                continue

        return float(prop) / total

    def yield_from_img_id(self, img_id, batch):
        '''
        helper function to yield data from a given shapefile for a specific img_id

        INPUT   img_id (str): ids of the images from which to generate patches from
                batch (int): number of chips to generate per iteration from the input
                    image id

        OUTPUT  Returns a generator object (g). calling g.next() returns the following:
                chips:
                    - one batch of masked (if True) chips
                    - corresponding feature_id for chips (if return_id is True)
                    - corresponding chip labels (if return_labels is True)

        EXAMPLE:
            $ g = get_iter_data('shapefile.geojson', batch-size=12)
            $ x,y = g.next()
            # x is the first 12 chips (of appropriate size) from the input shapefile
            # y is a list of classifications for the chips in x
        '''

        ct, inputs, labels, ids = 0, [], [], []
        cls_dict = {self.classes[i]: i for i in xrange(len(self.classes))}

        img = geoio.GeoImage(img_id + '.tif')
        for chip, properties in img.iter_vector(vector=self.shapefile,
                                                properties=True,
                                                filter=[{'image_id': img_id}],
                                                mask=self.mask):
            # check for adequate chip size
            if chip is None:
                continue
            chan, h, w = np.shape(chip)
            pad_h, pad_w = self.max_chip_hw - h, self.max_chip_hw - w
            if min(h, w) < self.min_chip_hw or max(h, w) > self.max_chip_hw:
                continue

            # zero-pad chip to standard net input size
            chip = chip.filled(0).astype(float)  # replace masked entries with zeros
            chip_patch = np.pad(chip, [(0, 0), (pad_h/2, (pad_h - pad_h/2)), (pad_w/2,
                (pad_w - pad_w/2))], 'constant', constant_values=0)

            if self.normalize:
                chip_patch /= 255.

            # get labels
            if self.return_labels:
                try:
                    label = properties['class_name']
                    if label is None:
                        continue
                    labels.append(cls_dict[label])
                except (TypeError, KeyError):
                    continue

            # get id
            if self.return_id:
                id = properties['feature_id']
                ids.append(id)

            inputs.append(chip_patch)
            ct += 1
            sys.stdout.write('\r%{0:.2f}'.format(100 * ct / float(batch)) + ' ' * 5)
            sys.stdout.flush()

            if ct == batch:
                data = [np.array([i for i in inputs])]

                if self.return_id:
                    data.append(ids)

                # Create one-hot encoded labels
                if self.return_labels:
                    Y = np.zeros((batch, len(self.classes)))
                    for i in range(batch):
                        Y[i, labels[i]] = 1
                    data.append(Y)
                yield data
                ct, inputs, labels, ids = 0, [], [], []

    def next(self):
        '''
        generate a batch of chips
        '''
        data = []

        # hit each generator in chip_gens
        for img_id, gen in self.chip_gens.iteritems():
            print '\nCollecting chips for image ' + str(img_id) + '...'
            data += zip(*gen.next())

        np.random.shuffle(data)
        return [np.array(i) for i in zip(*data)]
