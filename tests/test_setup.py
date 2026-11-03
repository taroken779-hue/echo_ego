"""Component separation and upgrade contracts without downloads or GPU work."""
import json
from pathlib import Path
import tempfile
import unittest

from configuration import ModelConfig, RuntimeConfig
from scripts.configure_setup import AUXILIARY, setup_config, validate_auxiliary
from scripts.download_auxiliary import download, MODELS
from scripts.register_qwen3 import model_config, validate_install
from store import Store


class SetupTests(unittest.TestCase):
    def test_new_qwen_install_has_no_omnivoice_model_or_paths(self):
        config = setup_config(None, 'qwen3')
        self.assertEqual(list(config.models), ['qwen3'])
        self.assertEqual(config.default_model, 'qwen3')
        self.assertNotIn('omnivoice', config.model_dump_json())
        for key, value in AUXILIARY.items():
            self.assertEqual(getattr(config, key), value)
        self.assertEqual(RuntimeConfig.model_validate_json(config.model_dump_json()), config)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(Store(folder, default_model=config.default_model).preferences().model_id, 'qwen3')

    def test_legacy_upgrade_retains_models_and_custom_settings(self):
        old = RuntimeConfig(port=8120, presets_dir='my-presets', preload=False)
        old.models['omnivoice'].model_path = 'existing/tts'
        old.translation_model = 'custom/translation'
        config = setup_config(old, 'qwen3')
        self.assertEqual(config.default_model, old.default_model)
        self.assertEqual(config.models['omnivoice'], old.models['omnivoice'])
        self.assertEqual(config.translation_model, 'custom/translation')
        self.assertEqual(config.asr_model, AUXILIARY['asr_model'])
        self.assertEqual((config.port, config.presets_dir, config.preload), (8120, 'my-presets', False))
        self.assertEqual(old.asr_model, 'runtime/omnivoice/asr')
        self.assertEqual(setup_config(config, 'qwen3'), config)

    def test_optional_omnivoice_cpu_preserves_qwen_default(self):
        config = setup_config(setup_config(None, 'qwen3'), 'omnivoice', cpu=True)
        self.assertEqual(config.default_model, 'qwen3')
        self.assertEqual(config.models['omnivoice'].precision, 'float32')
        self.assertEqual(config.models['omnivoice'].device, 'cpu')
        with self.assertRaises(ValueError):
            setup_config(None, 'qwen3', cpu=True)

    def test_auxiliary_downloader_only_fetches_auxiliary_repositories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            calls = []
            download(root, lambda repo, **kwargs: calls.append((repo, kwargs)))
            self.assertEqual({repo for repo, _ in calls}, set(MODELS))
            self.assertFalse((root/'runtime/omnivoice').exists())
            manifest = json.loads((root/'runtime/auxiliary/manifest.json').read_text())
            for repo, kwargs in calls:
                self.assertEqual(kwargs['revision'], MODELS[repo][1])
                self.assertEqual(manifest['models'][repo], kwargs['revision'])

    def test_auxiliary_upgrade_reuses_legacy_revisions_and_retains_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root/'runtime/omnivoice'
            for target, _ in MODELS.values():
                (legacy/target).mkdir(parents=True)
                (legacy/target/'model.safetensors').write_bytes(b'public-model')
            (legacy/'manifest.json').write_text(json.dumps({'models': {repo: 'old-revision' for repo in MODELS}}))
            calls = []
            download(root, lambda repo, **kwargs: calls.append(kwargs))
            for kwargs in calls:
                self.assertEqual(kwargs['revision'], 'old-revision')
                self.assertEqual((kwargs['local_dir']/'model.safetensors').read_bytes(), b'public-model')
            self.assertTrue((legacy/'asr/model.safetensors').exists())

    def test_auxiliary_download_pins_revision_before_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def interrupted(*args, **kwargs):
                raise OSError('interrupted')
            with self.assertRaises(OSError):
                download(root, interrupted)
            manifest = json.loads((root/'runtime/auxiliary/manifest.json').read_text())
            self.assertEqual(manifest['models'][next(iter(MODELS))], next(iter(MODELS.values()))[1])

    def test_partial_auxiliary_install_cannot_be_registered(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                validate_auxiliary(Path(folder))

    def test_qwen_registration_checks_revision_and_custom_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = model_config()
            for path in [model.python_path, model.model_path+'/model.safetensors']:
                dest = root/path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b'fixture')
            with self.assertRaisesRegex(SystemExit, 'revision'):
                validate_install(None, root)
            metadata = root/model.model_path/'.cache/huggingface/download/model.safetensors.metadata'
            metadata.parent.mkdir(parents=True)
            metadata.write_text('5d83992436eae1d760afd27aff78a71d676296fc\netag\n0')
            validate_install(None, root)
            self.assertTrue((root/model.manifest_path).is_file())
            config = setup_config(None, 'qwen3')
            config.models['qwen3'].model_path = 'custom/model'
            with self.assertRaisesRegex(SystemExit, 'not overwritten'):
                validate_install(config, root)


if __name__ == '__main__':
    unittest.main()
