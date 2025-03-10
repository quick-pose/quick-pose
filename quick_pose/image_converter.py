import shutil
from functools import partial
from pathlib import Path

import rawpy
from PIL import Image
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


def convert_and_resize_image(source_file_path: Path, dest_file_path: Path, target_dimension: int):
    if source_file_path.suffix.lower() in ('.nef',):
        raw = rawpy.imread(str(source_file_path))
        rgb = raw.postprocess()
        im = Image.fromarray(rgb)
    else:
        im = Image.open(source_file_path)

    rgb_im = im.convert('RGB')
    if target_dimension:
        rgb_im.thumbnail((target_dimension, target_dimension), Resampling.LANCZOS)
    rgb_im.save(dest_file_path)
    return True


def copy_and_convert_image(source_path: Path, dest_path: Path, overwrite: bool,
                           threshold_bytes: int, target_format: str, target_dimension: int,
                           source_file_path: Path):
    relative_source_path = source_file_path.relative_to(source_path)
    dest_file_path = dest_path.joinpath(relative_source_path).with_suffix(format_to_suffix(target_format))

    if not dest_file_path.parent.exists():
        dest_file_path.parent.mkdir(parents=True, exist_ok=True)

    if not dest_file_path.exists() or overwrite:
        if source_file_path.stat().st_size > threshold_bytes:
            convert_and_resize_image(source_file_path, dest_file_path, target_dimension)
            return 0, 1
        else:
            shutil.copy(source_file_path, dest_file_path)
            return 1, 0


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
              type=click.Choice(('jpg', 'jpeg', 'nef', 'png', 'tiff'), case_sensitive=False), multiple=True,
              default=('jpg', 'jpeg', 'nef', 'png', 'tiff'),
              help='source file conversion format')
@click.option('--target-format',
              type=click.Choice(('jpg', 'jpeg'), case_sensitive=False), default='jpg',
              help='target file conversion format')
@click.option('--target-dimension', type=int, default=0,
              help='target dimension in pixels on the largest axis')
@click.option('--max-tasks', default=0,
              help='number of tasks to run in parallel')
def convert(source_path: Path, dest_path: Path, overwrite: bool,
            threshold_size: str, source_format: str, target_format: str, target_dimension: int,
            max_tasks: int):
    threshold_bytes = dask.utils.parse_bytes(threshold_size)

    if max_tasks <= 0:
        import multiprocessing
        max_tasks = multiprocessing.cpu_count()

    cluster = LocalCluster(n_workers=max_tasks, processes=True)
    client = Client(cluster)

    files = list_files(source_path, source_format)
    futures = client.map(
        partial(
            copy_and_convert_image,
            source_path, dest_path, overwrite, threshold_bytes,
            target_format, target_dimension,
        ),
        list(files),
    )
    results = client.gather(futures)
    copied, converted = zip(*results)

    click.echo(f'Copied: {sum(copied)} files, converted: {sum(converted)} files')


if __name__ == '__main__':
    convert()
