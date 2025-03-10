import datetime
import json
import random
import shutil
from operator import itemgetter
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
import yadisk
from pelican import signals
from pelican.contents import Article
from pelican.readers import BaseReader


def add_article(article_generator):
    settings = article_generator.settings

    (
        yadisk_path_prefix,
        yadisk_listings_path,
        yandex_client_id,
        yandex_client_secret,
        yandex_access_token,
        content_path,
        images_path,
        images_number_per_category,
        categories,
    ) = itemgetter(
        'YADISK_PATH_PREFIX',
        'YADISK_LISTINGS_PATH',
        'YANDEX_CLIENT_ID',
        'YANDEX_CLIENT_SECRET',
        'YANDEX_ACCESS_TOKEN',
        'PATH',
        'IMAGES_PATH',
        'IMAGES_NUMBER_PER_CATEGORY',
        'CATEGORIES',
    )(settings)

    ya_client = yadisk.Client(yandex_client_id, yandex_client_secret, yandex_access_token)
    with ya_client, TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        assert ya_client.check_token()
        listing_files = [
            Path(obj.path[len(yadisk_path_prefix):])
            for obj in ya_client.listdir(f'{yadisk_path_prefix}{yadisk_listings_path}')
            if obj.is_file()
        ]
        base_reader = BaseReader(settings)

        for listing_file in listing_files:
            category = listing_file.stem
            if categories and category not in categories:
                print(f'Skipping {listing_file}, category {category} is not whitelisted')
                continue

            local_filepath = tmppath.joinpath(listing_file.name)
            ya_client.download(f'/{str(listing_file)}', str(local_filepath))
            with open(local_filepath, mode='r', encoding='utf-8') as fp:
                images = []
                lines = fp.readlines()
                selected_images = random.sample(lines, min(len(lines), images_number_per_category))
                print(
                    f'Categoy {category} has total images count: {len(lines)}, '
                    f'needed: {images_number_per_category}, selected: {len(selected_images)}')
                for line in selected_images:
                    image_details = json.loads(line)
                    r = requests.get(image_details['original_url'], allow_redirects=True, stream=True)
                    if not r.ok:
                        print(f'Could not download image: {image_details["original_url"]}, '
                              f'status: {r.status_code}: {r.text}')
                        continue
                    root_path, obj_path = Path(image_details['root_path']), Path(image_details['obj_path'])
                    image_path = obj_path.relative_to(root_path)
                    image_filepath = content_path / Path(images_path) / image_path
                    image_filepath.parent.mkdir(parents=True, exist_ok=True)
                    image_url = f'{images_path}/{image_path}'
                    with open(image_filepath, 'wb') as f:
                        shutil.copyfileobj(r.raw, f)
                    images.append(image_url)

                if images:
                    print(f'Selected images count: {len(images)}')
                    new_article = Article('', {
                        'template': 'lightbox',
                        'title': category,
                        'date': datetime.datetime.now(),
                        'category': base_reader.process_metadata('category', category),
                        'images': images,
                    })
                    article_generator.articles.insert(0, new_article)
                else:
                    print(f'No images selected for {category}, skipping article')


def register():
    signals.article_generator_pretaxonomy.connect(add_article)
