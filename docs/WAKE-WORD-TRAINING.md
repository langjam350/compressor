# Training the "compressor" Wake-Word Model

Compressor's Phase-1 wake-word detection uses [openWakeWord](https://github.com/dscripka/openWakeWord),
which streams microphone audio through a small local neural network — far
more reliable than the cloud-STT fallback, and fully offline.

openWakeWord has no pretrained "compressor" model, so you train one yourself.
It's a one-time step: the training notebook synthesizes thousands of spoken
"compressor" examples with text-to-speech (you don't record anything), trains
against a large negative dataset, and hands you a small model file.

**Time:** roughly 30-60 minutes in Google Colab's free GPU tier.
**Cost:** free (Google account required for Colab).

## Steps

1. Open the simple training notebook in Google Colab:

   https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb?usp=sharing

   (Linked from the openWakeWord README as the "simple" notebook. If the link
   ever goes stale, the detailed alternative lives in the repo at
   `notebooks/automatic_model_training.ipynb` — same output, more knobs.)

2. In Colab: **Runtime → Change runtime type → GPU** (T4 is fine), then run
   the cells top to bottom.

3. When prompted for the target wake word/phrase, enter:

   ```
   compressor
   ```

4. Let it run. It generates synthetic positive clips, mixes in negative/noise
   data, trains, and produces model files — you want the **`.onnx`** one
   (a `.tflite` is produced too; we use ONNX on Windows).

5. Download the `.onnx` file and save it in this repo as:

   ```
   models/compressor.onnx
   ```

   (The exact filename matters — it's the default `wake_model_path` in
   `config.yaml`. If you name it differently, update `wake_model_path`.)

6. Restart the assistant (`py main.py`). On startup you should see:

   ```
   [Compressor] Wake model loaded; listening for 'compressor'...
   ```

   instead of the "Wake model not found" fallback message.

## Tuning

- `wake_threshold` in `config.yaml` (default `0.5`): the detection score
  (0-1) required to trigger. If it misses your voice, lower it (e.g. `0.4`);
  if it false-wakes on TV/conversation, raise it (e.g. `0.6`-`0.7`).
- If quality is poor, re-run the notebook with more generated samples
  (the detailed notebook exposes this directly).

## Follower units

Each unit detects the wake word locally, so copy the same
`models/compressor.onnx` to every follower machine's repo checkout as well.
