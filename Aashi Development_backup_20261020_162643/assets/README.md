# Assets

Static files that ship with Aashi.

```
icons/    application and UI icons
fonts/    bundled fonts
images/   raster images and illustrations
```

Assets are located exclusively through `aashi.paths`:

```python
from aashi.paths import resolve_paths

paths = resolve_paths()
icon_path = paths.asset("icons", "aashi.svg")
```

Never build an asset path with a literal or relative string — resolution differs
between a source run and a packaged build, and `aashi.paths` is the only place
that knows the difference.

Empty subdirectories are kept in Git with `.gitkeep` files; delete those once a
directory holds real assets.
