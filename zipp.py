import io
import posixpath
import zipfile
import functools
import itertools
from collections import OrderedDict


def _parents(path):
    """
    Given a path with elements separated by
    posixpath.sep, generate all parents of that path.

    >>> list(_parents('b/d'))
    ['b']
    >>> list(_parents('/b/d/'))
    ['/b']
    >>> list(_parents('b/d/f/'))
    ['b/d', 'b']
    >>> list(_parents('b'))
    []
    >>> list(_parents(''))
    []
    """
    return itertools.islice(_ancestry(path), 1, None)


def _ancestry(path):
    """
    Given a path with elements separated by
    posixpath.sep, generate all elements of that path

    >>> list(_ancestry('b/d'))
    ['b/d', 'b']
    >>> list(_ancestry('/b/d/'))
    ['/b/d', '/b']
    >>> list(_ancestry('b/d/f/'))
    ['b/d/f', 'b/d', 'b']
    >>> list(_ancestry('b'))
    ['b']
    >>> list(_ancestry(''))
    []
    """
    path = path.rstrip(posixpath.sep)
    while path and path != posixpath.sep:
        yield path
        path, tail = posixpath.split(path)


class FastZip:
    """
    Wrapper around a zipfile.ZipFile to ensure implicit
    dirs exist and are resolved rapidly.
    """
    def __init__(self, zipfile):
        self.zipfile = zipfile
        self.__names = zipfile.namelist()
        self.__names += self._implied_dirs(self.__names)
        self.__lookup = set(self.__names)

    def __getattr__(self, *args, **kwargs):
        return getattr(self.zipfile, *args, **kwargs)

    def find(self, name):
        if name not in self.__lookup and name + '/' in self.__lookup:
            return name + '/'
        return name

    @staticmethod
    def _implied_dirs(names):
        parents = itertools.chain.from_iterable(map(_parents, names))
        # Deduplicate entries in original order
        implied_dirs = OrderedDict.fromkeys(
            p + posixpath.sep for p in parents
            # Cast names to a set for O(1) lookups
            if p + posixpath.sep not in set(names)
        )
        return implied_dirs

    def namelist(self):
        return self.__names


class Path:
    """
    A pathlib-compatible interface for zip files.

    Consider a zip file with this structure::

        .
        ├── a.txt
        └── b
            ├── c.txt
            └── d
                └── e.txt

    >>> data = io.BytesIO()
    >>> zf = zipfile.ZipFile(data, 'w')
    >>> zf.writestr('a.txt', 'content of a')
    >>> zf.writestr('b/c.txt', 'content of c')
    >>> zf.writestr('b/d/e.txt', 'content of e')
    >>> zf.filename = 'abcde.zip'

    Path accepts the zipfile object itself or a filename

    >>> root = Path(zf)

    From there, several path operations are available.

    Directory iteration (including the zip file itself):

    >>> a, b = root.iterdir()
    >>> a
    Path('abcde.zip', 'a.txt')
    >>> b
    Path('abcde.zip', 'b/')

    name property:

    >>> b.name
    'b'

    join with divide operator:

    >>> c = b / 'c.txt'
    >>> c
    Path('abcde.zip', 'b/c.txt')
    >>> c.name
    'c.txt'

    Read text:

    >>> c.read_text()
    'content of c'

    existence:

    >>> c.exists()
    True
    >>> (b / 'missing.txt').exists()
    False

    Coercion to string:

    >>> str(c)
    'abcde.zip/b/c.txt'
    """

    __repr = "{self.__class__.__name__}({self.root.filename!r}, {self.at!r})"

    def __init__(self, root, at=""):
        self.root = (
            root
            if isinstance(root, FastZip) else
            FastZip(
                root
                if isinstance(root, zipfile.ZipFile)
                else zipfile.ZipFile(self._pathlib_compat(root))
            )
        )
        self.at = at

    @staticmethod
    def _pathlib_compat(path):
        """
        For path-like objects, convert to a filename for compatibility
        on Python 3.6.1 and earlier.
        """
        try:
            return path.__fspath__()
        except AttributeError:
            return str(path)

    @property
    def open(self):
        return functools.partial(self.root.open, self.at)

    @property
    def name(self):
        return posixpath.basename(self.at.rstrip("/"))

    def read_text(self, *args, **kwargs):
        with self.open() as strm:
            return io.TextIOWrapper(strm, *args, **kwargs).read()

    def read_bytes(self):
        with self.open() as strm:
            return strm.read()

    def _is_child(self, path):
        return posixpath.dirname(path.at.rstrip("/")) == self.at.rstrip("/")

    def _next(self, at):
        return Path(self.root, at)

    def is_dir(self):
        return not self.at or self.at.endswith("/")

    def is_file(self):
        return not self.is_dir()

    def exists(self):
        return self.at in self.root.namelist()

    def iterdir(self):
        if not self.is_dir():
            raise ValueError("Can't listdir a file")
        subs = map(self._next, self.root.namelist())
        return filter(self._is_child, subs)

    def __str__(self):
        return posixpath.join(self.root.filename, self.at)

    def __repr__(self):
        return self.__repr.format(self=self)

    def joinpath(self, add):
        add = self._pathlib_compat(add)
        next = posixpath.join(self.at, add)
        return self._next(self.root.find(next))

    __truediv__ = joinpath

    @property
    def parent(self):
        parent_at = posixpath.dirname(self.at.rstrip('/'))
        if parent_at:
            parent_at += '/'
        return self._next(parent_at)
