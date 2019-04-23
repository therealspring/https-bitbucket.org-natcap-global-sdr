"""Script to run a global SDR analysis."""
import glob
import urllib
import shutil
import re
import hashlib
import datetime
import os
import zipfile
import logging
import sys

import taskgraph


WORKSPACE_DIR = 'workspace'
CHURN_DIR = os.path.join(WORKSPACE_DIR, 'churn')
ECOSHARD_DIR = os.path.join(CHURN_DIR, 'ecoshards')

N_CPUS = 4
TASKGRAPH_REPORTING_FREQUENCY = 5.0

logging.basicConfig(
    level=logging.DEBUG,
    format=(
        '%(asctime)s (%(relativeCreated)d) %(levelname)s %(name)s'
        ' [%(funcName)s:%(lineno)d] %(message)s'),
    stream=sys.stdout)
LOGGER = logging.getLogger(__name__)

EROSIVITY_URL = r'https://storage.googleapis.com/global-invest-sdr-data/erosivity_CIAT_50km_md5_8e0d84d5736d118e111b8ee0ded65358.tif'
ERODIBILITY_URL = r'https://storage.googleapis.com/global-invest-sdr-data/erodibility_globe_ISRIC_30arcseconds_md5_e3f8961b77539b686deb9a3d04ee4ce3.tif'
LULC_URL = r'https://storage.googleapis.com/ipbes-ndr-ecoshard-data/ESACCI-LC-L4-LCCS-Map-300m-P1Y-2015-v2.0.7_md5_1254d25f937e6d9bdee5779d377c5aa4.tif'
DEM_URL = r'https://storage.googleapis.com/global-invest-sdr-data/global_dem_3s_md5_22d0c3809af491fa09d03002bdf09748.zip'
WATERSHEDS_URL = r'https://storage.googleapis.com/global-invest-sdr-data/watersheds_globe_HydroSHEDS_15arcseconds_md5_c6acf2762123bbd5de605358e733a304.zip'
BIOPHYSICAL_TABLE_URL = r'https://storage.googleapis.com/global-invest-sdr-data/Biophysical_table_ESA_ARIES_RS_md5_e16587ebe01db21034ef94171c76c463.csv'


def main():
    """Entry point."""
    for dir_path in [
            WORKSPACE_DIR, CHURN_DIR, ECOSHARD_DIR]:
        try:
            os.makedirs(dir_path)
        except OSError:
            pass

    task_graph = taskgraph.TaskGraph(
        os.path.join(WORKSPACE_DIR, 'taskgraph_cache'), N_CPUS,
        TASKGRAPH_REPORTING_FREQUENCY)

    lulc_path = os.path.join(ECOSHARD_DIR, os.path.basename(LULC_URL))
    fetch_lulc_task = task_graph.add_task(
        func=url_fetch_and_validate,
        args=(LULC_URL, lulc_path),
        target_path_list=[lulc_path],
        task_name='fetch lulc raster')

    erosivity_path = os.path.join(
        ECOSHARD_DIR, os.path.basename(EROSIVITY_URL))
    fetch_erosivity_task = task_graph.add_task(
        func=url_fetch_and_validate,
        args=(EROSIVITY_URL, erosivity_path),
        target_path_list=[erosivity_path],
        task_name='fetch erosivity raster')

    erodibility_path = os.path.join(
        ECOSHARD_DIR, os.path.basename(ERODIBILITY_URL))
    fetch_erodibility_task = task_graph.add_task(
        func=url_fetch_and_validate,
        args=(ERODIBILITY_URL, erodibility_path),
        target_path_list=[erodibility_path],
        task_name='fetch erodibility raster')

    biophysical_table_path = os.path.join(
        ECOSHARD_DIR, os.path.basename(BIOPHYSICAL_TABLE_URL))
    fetch_biophysical_table_task = task_graph.add_task(
        func=url_fetch_and_validate,
        args=(BIOPHYSICAL_TABLE_URL, biophysical_table_path),
        target_path_list=[biophysical_table_path],
        task_name='fetch biophysical_table raster')

    dem_token_path = os.path.join(
        ECOSHARD_DIR, '%s.COMPLETE' % os.path.basename(DEM_URL))
    fetch_dem_task = task_graph.add_task(
        func=download_validate_and_unzip,
        args=(DEM_URL, ECOSHARD_DIR, dem_token_path),
        target_path_list=[dem_token_path],
        task_name='fetch dem raster')

    watersheds_token_path = os.path.join(
        ECOSHARD_DIR, '%s.COMPLETE' % os.path.basename(WATERSHEDS_URL))
    fetch_watersheds_task = task_graph.add_task(
        func=download_validate_and_unzip,
        args=(WATERSHEDS_URL, ECOSHARD_DIR, watersheds_token_path),
        target_path_list=[watersheds_token_path],
        task_name='fetch watersheds shapefile')

    fetch_watersheds_task.join()

    for watershed_path in glob.glob(os.path.join(
            ECOSHARD_DIR, 'watersheds_globe_HydroSHEDS_15arcseconds',
            '*.shp')):
        LOGGER.debug(watershed_path)

    task_graph.close()


def download_validate_and_unzip(url, target_dir, token_file):
    """Download url to target and write a token file when it unzips."""
    target_path = os.path.join(target_dir, os.path.basename(url))
    url_fetch_and_validate(url, target_path)
    with zipfile.ZipFile(target_path, 'r') as zip_ref:
        zip_ref.extractall(os.path.dirname(target_path))
    with open(token_file, 'w') as token_file:
        token_file.write(str(datetime.datetime.now()))


def url_fetch_and_validate(url, target_path):
    """Download a Google Blob to a given path and hash.

    Parameters:
        url (string): url to a file to fetch.
        target_path (string): path to download the file into, must match
            an embedded hash/algorithm pair.

    Raises:
        ValueError if downloaded file does not match its embedded fingerprint
            where the filename is of the form
            [filename]_[hash_alg]_[fingerprint].ext

    Returns:
        None.

    """
    url_fetcher(url, target_path)
    if not valid_hash(target_path, 'embedded'):
        raise ValueError("%s does not match its expected hash" % target_path)


def url_fetcher(url, path):
    """Download `url` to `path`."""
    LOGGER.info('fetching %s' % path)
    response = urllib.urlopen(url)
    with open(path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)
    response.close()


def valid_hash(file_path, expected_hash, buf_size=2**20):
    """Validate that the file at `file_path` matches `expected_hash`.

    Parameters:
        file_path (str): path to file location on disk.
        expected_hash (str or tuple): if a tuple, a "hash algorithm",
            "expected_hash" pair that will be used to hash `expected_path`
            and confirm that the hash of that file is equivalent to the
            expected hash value. If the `expected_path` does not
            match the hash, this function will raise an AssertionError.

            Otherwise must be the value "embedded" which attempts to parse
            `file_path` for the pattern
            filename_{hash_algorthm}_{hash_value}.{rest of filename}.
        buf_size (int): (optional) number of bytes to read from `file_path`
            at a time for digesting.

    Returns:
        True if `file_path` hashes to `expected_hash`.

    Raises:
        ValueError if `expected_hash == 'embedded'` and `file_path` does not
        match the appropriate file pattern.

        IOError if `file_path` not found.

    """
    if not os.path.exists(file_path):
        raise IOError('%s not found.' % file_path)
    if isinstance(expected_hash, tuple):
        hash_algorithm = expected_hash[0]
        expected_hash_value = expected_hash[1]
    elif expected_hash == 'embedded':
        hash_re_pattern = r'.*_([^_]+)_([0-9a-f]+)\.[^_]*$'
        hash_match = re.match(hash_re_pattern, file_path)
        if not hash_match:
            raise ValueError(
                "file_path: %s did not end "
                "in an [hash_alg]_[hexhash][.ext] format" % {file_path})
        hash_algorithm = hash_match.group(1)
        expected_hash_value = hash_match.group(2)
    else:
        raise ValueError(
            "Invalid value for `expected_hash`, expecting either a tuple "
            "or 'embedded': {expected_hash}")

    actual_hash = hash_file(file_path, hash_algorithm)
    return expected_hash_value == actual_hash


def hash_file(file_path, hash_algorithm, buf_size=2**20):
    """Return a hex  digest of `file_path`.

    Parameters:
        file_path (string): path to file to hash.
        hash_algorithm (string): a hash function id that exists in
            hashlib.algorithms_available.
        buf_size (int): number of bytes to read from `file_path` at a time
            for digesting.

    Returns:
        a (hash, crc32) hex digest tuple with hash algorithm `hash_algorithm`
        of the binary contents of `file_path` and the crc32 checksum of that
        file.

    """
    hash_func = hashlib.new(hash_algorithm)
    with open(file_path, 'rb') as f:
        binary_data = f.read(buf_size)
        while binary_data:
            hash_func.update(binary_data)
            binary_data = f.read(buf_size)
    return hash_func.hexdigest()[:32]


if __name__ == '__main__':
    main()