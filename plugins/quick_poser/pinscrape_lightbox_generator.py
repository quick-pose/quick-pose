import datetime
import multiprocessing
import random
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from operator import itemgetter
from pathlib import Path
from tempfile import TemporaryDirectory
from pelican import signals
from pelican.contents import Article
from pelican.readers import BaseReader
from pinscrape.pinscrape import PinterestImageScraper


class ReliablePinterestImageScraper(PinterestImageScraper):
    def download(self, url_list, num_of_workers, output_folder):
        param = [
            (url_list[i:i + num_of_workers], output_folder)
            for i in range(0, len(url_list), num_of_workers)
        ]
        with ThreadPoolExecutor(max_workers=num_of_workers) as executor:
            executor.map(self.saving_op, param)
            executor.shutdown(wait=True)


scraper = ReliablePinterestImageScraper()


def _download(category: str, query: str, max_images: int, categories: [str], tmppath: Path):
    download_filepaths = []
    if categories and category not in categories:
        print(f'Skipping query {query}, category {category} is not whitelisted')
        return download_filepaths

    details = scraper.scrape(
        query, str(tmppath), {}, multiprocessing.cpu_count(), max_images)

    import time
    time.sleep(10)

    if details.get('isDownloaded', False):
        print(f'Found {len(details["extracted_urls"])} urls for query {query}, '
              f'downloaded {len(details["urls_list"])}')
        download_filepaths = list(tmppath.iterdir())
        print(f'Downloaded {len(download_filepaths)} files')
    else:
        print(f'Skipping query {query}, nothing downloaded', details)
    return download_filepaths


def add_article(article_generator):
    settings = article_generator.settings

    (
        pinscrape_queries_by_categories,
        content_path,
        images_path,
        images_number_per_category,
        categories,
    ) = itemgetter(
        'PINSCRAPE_QUERIES_BY_CATEGORIES',
        'PATH',
        'IMAGES_PATH',
        'IMAGES_NUMBER_PER_CATEGORY',
        'CATEGORIES',
    )(settings)

    queries = [(category, query) for category, queries in pinscrape_queries_by_categories.items() for query in queries]

    with TemporaryDirectory() as tmpdir:
        root_tmppath = Path(tmpdir)
        download_filepaths = defaultdict(list)
        for query_idx, (category, query) in enumerate(queries):
            tmppath = root_tmppath.joinpath(f'{category}{query_idx}')
            download_filepaths[category].extend(_download(
                category, query, images_number_per_category * 3, categories, tmppath))

        base_reader = BaseReader(settings)

        for category, image_filepaths in download_filepaths.items():
            selected_images = random.sample(image_filepaths, min(len(image_filepaths), images_number_per_category))

            print(
                f'Category {category} has total images count: {len(image_filepaths)}, '
                f'needed: {images_number_per_category}, selected: {len(selected_images)}')

            images = []
            for image_tmp_filepath in selected_images:
                image_path = f'{category}/{image_tmp_filepath.name}'
                image_filepath = content_path / Path(images_path) / image_path
                image_filepath.parent.mkdir(parents=True, exist_ok=True)
                image_url = f'{images_path}/{image_path}'
                images.append(image_url)
                shutil.move(image_tmp_filepath, image_filepath)

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
