AUTHOR = 'Me'
SITENAME = 'Quick Pose'
SITEURL = ""

PATH = "content"

TIMEZONE = 'Europe/Rome'

DEFAULT_LANG = 'en'

# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Blogroll
LINKS = ()

# Social widget
SOCIAL = ()

DEFAULT_PAGINATION = False

TAGS_SAVE_AS = ''
TAG_SAVE_AS = ''

IMAGES_PATH = 'images'
ASSETS_PATH = 'assets'

STATIC_PATHS = [IMAGES_PATH, ASSETS_PATH, 'robots.txt']

THEME_TEMPLATES_OVERRIDES = ['templates']

# Uncomment following line if you want document-relative URLs when developing
# RELATIVE_URLS = True

IMAGES_NUMBER_PER_CATEGORY = 1

SLIDER_DEFAULT_VALUE = 180
SLIDER_RANGE = '10,300'
SLIDER_VALUES = '10,20,30,60,120,180,300'

CATEGORIES = ()

YADISK_PATH_PREFIX = 'disk:/'
YADISK_LISTINGS_PATH = ''
YANDEX_CLIENT_ID = ''
YANDEX_CLIENT_SECRET = ''
YANDEX_ACCESS_TOKEN = ''

from plugins.quick_poser import lightbox_generator

lightbox_generator.register()
PLUGINS = [lightbox_generator]
