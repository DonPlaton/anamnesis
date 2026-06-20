# Demo

`examples/demo.sh` is a self-contained 25-second demo. It seeds a throwaway store with three
lessons, then shows a fresh query recalling the right one (and abstaining on nonsense). Your real
vault is never touched.

```bash
bash examples/demo.sh          # run it (best with Ollama running → semantic recall)
```

## Recording the README GIF

```bash
# 1. record (https://github.com/asciinema/asciinema)
asciinema rec -c "bash examples/demo.sh" demo.cast

# 2. render to GIF (https://github.com/asciinema/agg)
agg --theme monokai --speed 1.3 demo.cast docs/demo.gif
```

The README embeds `docs/demo.gif`. Keep it under ~3 MB so it loads inline on GitHub. Aim for the
"it remembered" beat (step ②) to land in the first few seconds. That's the moment that earns the star.
