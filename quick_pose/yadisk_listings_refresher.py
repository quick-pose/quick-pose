import json
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TextIO

import click
import yadisk

from dask.distributed import Client
from dask.distributed import LocalCluster
from yadisk.exceptions import PathNotFoundError

YA_DISK_PATH_PREFIX = 'disk:/'
CATEGORIES = {'Figure', 'Sculpture'}


def list_remote_files_itr(root_path: Path, source_path: Path, mime_types: [str],
                          ya_client: yadisk.Client, fp: TextIO) -> int:
    count = 0
    dirs = []
    for obj in ya_client.listdir(f'{YA_DISK_PATH_PREFIX}{source_path}'):
        assert obj.path.startswith(YA_DISK_PATH_PREFIX)
        obj_path = Path(obj.path[len(YA_DISK_PATH_PREFIX):])
        if obj.is_dir():
            dirs.append(obj_path)
        else:
            if obj.mime_type in mime_types:
                count += 1
                d = json.dumps({
                    'root_path': str(root_path),
                    'obj_path': str(obj_path),
                    'preview_url': obj.preview,
                    'original_url': obj.sizes['ORIGINAL'],
                })
                fp.write(d)
                fp.write('\n')

    for obj_path in dirs:
        count += list_remote_files_itr(root_path, obj_path, mime_types, ya_client, fp)

    return count


def list_remote_files(source_path: Path, mime_types: [str],
                      yandex_client_id: str, yandex_client_secret: str, yandex_access_token: str, tmppath: Path,
                      category: str) -> [str, [[Path, str]]]:
    print(f'Listing files for {category} in {source_path}')
    ya_client = yadisk.Client(yandex_client_id, yandex_client_secret, yandex_access_token)
    with ya_client, open(tmppath.joinpath(f'{category}.jsonl'), 'w') as fp:
        assert ya_client.check_token()
        category_source_path = source_path.joinpath(category)
        return category, list_remote_files_itr(source_path, category_source_path, mime_types, ya_client, fp)


def write_listings(dest_path: Path,
                   yandex_client_id: str, yandex_client_secret: str, yandex_access_token: str, tmppath: Path):
    print(f'Writing listings to {dest_path}')
    ya_client = yadisk.Client(yandex_client_id, yandex_client_secret, yandex_access_token)
    with ya_client:
        ya_path = f'{dest_path}'
        try:
            ya_client.remove(ya_path, permanently=True)
        except PathNotFoundError:
            pass
        ya_client.mkdir(ya_path)
        for path in tmppath.iterdir():
            ya_filepath = f'{dest_path.joinpath(path.relative_to(tmppath))}'
            print(f'Uploading to {ya_filepath}')
            ya_client.upload(str(path), ya_filepath)


class MultiChoiceWithJson(click.ParamType):
    name = "multi_choice_json"

    @staticmethod
    def flatten(values):
        for value in values:
            if isinstance(value, (list, tuple, set)):
                yield from MultiChoiceWithJson.flatten(value)
            else:
                yield value

    @staticmethod
    def normalize(allowed_values, ctx, param, value):
        value = set(list(MultiChoiceWithJson.flatten(value)))
        unknown_values = value.difference(allowed_values)
        if unknown_values:
            raise click.UsageError(f'Unknown values provided {", ".join(unknown_values)} for {param.name}.', ctx)
        return value

    def convert(self, value, param, ctx):
        try:
            value = json.loads(value)
            if not isinstance(value, list):
                raise click.UsageError('MultiChoiceWithJson only supports plain values '
                                       'or json encoded arrays.', ctx)
        except json.decoder.JSONDecodeError:
            pass
        return value


@click.command()
@click.option('--yadisk-source-path', required=True,
              type=click.Path(exists=False, file_okay=False, dir_okay=True, path_type=Path),
              help='source path on the remote disk')
@click.option('--yadisk-dest-path', required=True,
              type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
              help='destination path on the remote disk')
@click.option('--categories', required=True,
              callback=partial(MultiChoiceWithJson.normalize, CATEGORIES),
              type=MultiChoiceWithJson(), multiple=True,
              help='categories of files')
@click.option('--mime-types',
              type=click.Choice(('image/jpg', 'image/jpeg'), case_sensitive=False), multiple=True,
              default=('image/jpg', 'image/jpeg'),
              help='categories of files')
@click.option('--upload', is_flag=True, show_default=True, default=False,
              help='upload files to remote disk')
@click.option('--yandex-client-id', required=True,
              help='oauth client id')
@click.option('--yandex-client-secret', required=True,
              help='oauth client secret')
@click.option('--yandex-access-token', required=True,
              help='oauth access token')
@click.option('--max-tasks', default=0,
              help='number of tasks to run in parallel')
def refresh(yadisk_source_path: Path, yadisk_dest_path: Path,
            categories: [str],
            # categories_json: str,
            mime_types: [str], upload: bool,
            yandex_client_id: str, yandex_client_secret: str, yandex_access_token: str,
            max_tasks: int):
    if max_tasks <= 0:
        import multiprocessing
        max_tasks = multiprocessing.cpu_count()

    cluster = LocalCluster(n_workers=max_tasks, processes=True)
    client = Client(cluster)

    with TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        futures = client.map(
            partial(
                list_remote_files,
                yadisk_source_path, mime_types,
                yandex_client_id, yandex_client_secret, yandex_access_token,
                tmppath
            ),
            list(categories),
        )
        results = client.gather(futures)
        print([(category, r) for category, r in results])

        if upload:
            write_listings(
                yadisk_dest_path,
                yandex_client_id, yandex_client_secret, yandex_access_token,
                tmppath
            )


if __name__ == '__main__':
    refresh()
