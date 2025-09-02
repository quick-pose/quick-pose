import shutil
from functools import partial
from pathlib import Path

import pillow_heif
import rawpy
from PIL import Image, ImageOps
from PIL.Image import Resampling
from dask.distributed import Client
from dask.distributed import LocalCluster
import click
import dask.utils


def format_to_suffix(format: str):
    return f'.{format.lstrip(".").lower()}'


def list_files(source_path: Path, source_format: str):
    source_format = [format_to_suffix(f) for f in source_format]
    for path in source_path.glob('**/*'):
        if path.suffix.lower() in source_format:
            yield path


def convert_and_resize_image(
        source_file_path: Path, dest_file_path: Path, target_dimension: int = 0, target_filesize: int = 0
):
    if source_file_path.suffix.lower() in ('.nef',):
        raw = rawpy.imread(str(source_file_path))
        rgb = raw.postprocess()
        im = Image.fromarray(rgb)
    elif source_file_path.suffix.lower() in ('.heic',) and not pillow_heif.is_supported(source_file_path):
        click.echo(f'Image {source_file_path} is not supported')
        return False
    else:
        im = Image.open(source_file_path)

    im = ImageOps.exif_transpose(im)
    rgb_im = im.convert('RGB')
    if target_dimension:
        rgb_im.thumbnail((target_dimension, target_dimension), Resampling.LANCZOS)

    # Implement target_filesize if specified, otherwise save with default quality
    if target_filesize:
        # Try JPEG quality settings to fit into file size, binary search approach
        quality_min, quality_max = 20, 95
        quality = quality_max
        last_good_bytes = None
        last_good_quality = None
        for _ in range(10):  # Limit iterations
            rgb_im.save(dest_file_path, format="JPEG", quality=quality)
            size = dest_file_path.stat().st_size
            if size <= target_filesize:
                last_good_bytes = size
                last_good_quality = quality
                if target_filesize - size < 3000:  # Within 3KB is close enough, stop early
                    break
                quality_min = quality + 1
            else:
                quality_max = quality - 1
            if quality_min > quality_max:
                break
            quality = (quality_min + quality_max) // 2
        # If never managed to reach filesize, save with minimal quality tried
        if last_good_quality is not None:
            rgb_im.save(dest_file_path, format="JPEG", quality=last_good_quality)
    else:
        rgb_im.save(dest_file_path, format="JPEG")
    return True


def copy_and_convert_image(source_path: Path, dest_path: Path, overwrite: bool,
                           threshold_bytes: int, target_format: str, target_dimension: int,
                           target_filesize: int,  # NEW
                           source_file_path: Path):
    relative_source_path = source_file_path.relative_to(source_path)
    dest_file_path = dest_path.joinpath(relative_source_path).with_suffix(format_to_suffix(target_format))

    if not dest_file_path.parent.exists():
        dest_file_path.parent.mkdir(parents=True, exist_ok=True)

    if not dest_file_path.exists() or overwrite:
        if source_file_path.stat().st_size > threshold_bytes:
            try:
                res = convert_and_resize_image(
                    source_file_path, dest_file_path, target_dimension=target_dimension, target_filesize=target_filesize
                )
                return (1, 0)[res], 0, (0, 1)[res]
            except Exception as e:
                click.echo(f'Failed processing image {source_path}: {str(e)}')
                return 1, 0, 0
        else:
            shutil.copy(source_file_path, dest_file_path)
            return 0, 1, 0

    return 0, 0, 0


@click.command()
@click.option('--source-path', required=True,
              type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
              help='source path')
@click.option('--dest-path', required=True,
              type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
              help='destination path')
@click.option('--overwrite', is_flag=True, show_default=True, default=False,
              help='overwrite files at destination')
@click.option('--threshold-size', default='1Mb',
              help='filesize threshold to include for a conversion')
@click.option('--source-format',
              type=click.Choice(('heic', 'jpg', 'jpeg', 'nef', 'png', 'tiff'), case_sensitive=False),
              multiple=True,
              default=('heic', 'jpg', 'jpeg', 'nef', 'png', 'tiff'),
              help='source file conversion format')
@click.option('--target-format',
              type=click.Choice(('jpg', 'jpeg'), case_sensitive=False), default='jpg',
              help='target file conversion format')
@click.option('--target-dimension', type=int, default=0,
              help='target dimension in pixels on the largest axis')
@click.option('--target-filesize', default='', help='target filesize (e.g., 500Kb, 2Mb)')
@click.option('--max-tasks', default=0,
              help='number of tasks to run in parallel')
def convert(source_path: Path, dest_path: Path, overwrite: bool,
            threshold_size: str, source_format: str, target_format: str, target_dimension: int,
            target_filesize: str,
            max_tasks: int):
    if 'heic' in source_format:
        click.echo('Registering heif opener')
        pillow_heif.register_heif_opener()

    threshold_bytes = dask.utils.parse_bytes(threshold_size)
    target_filesize_bytes = 0
    if target_filesize:
        target_filesize_bytes = dask.utils.parse_bytes(target_filesize)

    if max_tasks <= 0:
        import multiprocessing
        max_tasks = multiprocessing.cpu_count()

    cluster = LocalCluster(n_workers=max_tasks, processes=True)
    client = Client(cluster)

    click.echo(f'Listing source files')
    files = list_files(source_path, source_format)
    files = list(files)
    click.echo(f'Discovered {len(files)} files')

    futures = client.map(
        partial(
            copy_and_convert_image,
            source_path, dest_path, overwrite, threshold_bytes,
            target_format, target_dimension, target_filesize_bytes,
        ),
        files,
    )
    results = client.gather(futures)
    failed, copied, converted = zip(*results)

    click.echo(f'Copied: {sum(copied)} files, converted: {sum(converted)} files')


if __name__ == '__main__':
    convert()
