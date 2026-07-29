package com.mlomega.xr.documents;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import com.unity3d.player.UnityPlayer;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Tiny Storage Access Framework proxy. Only a user-selected JSON document is
 * copied; neither APK receives broad storage permission.
 */
public final class WorldMapDocumentActivity extends Activity {
    private static final int REQUEST = 4731;
    private static final long MAX_BYTES = 768L * 1024L * 1024L;

    public static void beginExport(
            String sourcePath,
            String displayName,
            String callbackObject) {
        Intent proxy = new Intent(
                UnityPlayer.currentActivity,
                WorldMapDocumentActivity.class);
        proxy.putExtra("mode", "export");
        proxy.putExtra("path", sourcePath);
        proxy.putExtra("name", displayName);
        proxy.putExtra("callback", callbackObject);
        UnityPlayer.currentActivity.startActivity(proxy);
    }

    public static void beginImport(
            String destinationPath,
            String callbackObject) {
        Intent proxy = new Intent(
                UnityPlayer.currentActivity,
                WorldMapDocumentActivity.class);
        proxy.putExtra("mode", "import");
        proxy.putExtra("path", destinationPath);
        proxy.putExtra("callback", callbackObject);
        UnityPlayer.currentActivity.startActivity(proxy);
    }

    public static void beginImageImport(
            String destinationPath,
            String callbackObject) {
        Intent proxy = new Intent(
                UnityPlayer.currentActivity,
                WorldMapDocumentActivity.class);
        proxy.putExtra("mode", "image");
        proxy.putExtra("path", destinationPath);
        proxy.putExtra("callback", callbackObject);
        UnityPlayer.currentActivity.startActivity(proxy);
    }

    public static void beginGlbImport(
            String destinationPath,
            String callbackObject) {
        Intent proxy = new Intent(
                UnityPlayer.currentActivity,
                WorldMapDocumentActivity.class);
        proxy.putExtra("mode", "glb");
        proxy.putExtra("path", destinationPath);
        proxy.putExtra("callback", callbackObject);
        UnityPlayer.currentActivity.startActivity(proxy);
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String mode = getIntent().getStringExtra("mode");
        Intent intent;
        if ("export".equals(mode)) {
            intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.setType("application/json");
            intent.putExtra(
                    Intent.EXTRA_TITLE,
                    getIntent().getStringExtra("name"));
        } else if ("image".equals(mode)) {
            intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.setType("image/*");
            intent.putExtra(
                    Intent.EXTRA_MIME_TYPES,
                    new String[] { "image/png", "image/jpeg" });
            intent.addCategory(Intent.CATEGORY_OPENABLE);
        } else if ("glb".equals(mode)) {
            intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.setType("model/gltf-binary");
            intent.putExtra(
                    Intent.EXTRA_MIME_TYPES,
                    new String[] {
                        "model/gltf-binary",
                        "application/octet-stream"
                    });
            intent.addCategory(Intent.CATEGORY_OPENABLE);
        } else {
            intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.setType("application/json");
            intent.addCategory(Intent.CATEGORY_OPENABLE);
        }
        startActivityForResult(intent, REQUEST);
    }

    @Override
    protected void onActivityResult(
            int requestCode,
            int resultCode,
            Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST || resultCode != RESULT_OK ||
                data == null || data.getData() == null) {
            reply("cancelled", "");
            finish();
            return;
        }
        Uri uri = data.getData();
        String mode = getIntent().getStringExtra("mode");
        String path = getIntent().getStringExtra("path");
        try {
            if ("export".equals(mode)) {
                File source = new File(path);
                if (!source.isFile() || source.length() > MAX_BYTES)
                    throw new IllegalArgumentException("source_unbounded");
                try (
                    InputStream input = new FileInputStream(source);
                    OutputStream output =
                        getContentResolver().openOutputStream(uri, "wt")
                ) {
                    copyBounded(input, output);
                }
                reply("exported", uri.toString());
            } else {
                File destination = new File(path);
                File parent = destination.getParentFile();
                if (parent != null) parent.mkdirs();
                try (
                    InputStream input = getContentResolver().openInputStream(uri);
                    OutputStream output = new FileOutputStream(destination, false)
                ) {
                    copyBounded(input, output);
                }
                reply(
                        "image".equals(mode)
                            ? "image_imported"
                            : "glb".equals(mode)
                                ? "glb_imported"
                                : "imported",
                        destination.getAbsolutePath());
            }
        } catch (Exception error) {
            reply("error", error.getClass().getSimpleName());
        }
        finish();
    }

    private static void copyBounded(InputStream input, OutputStream output)
            throws Exception {
        if (input == null || output == null)
            throw new IllegalArgumentException("stream_unavailable");
        byte[] buffer = new byte[16 * 1024];
        long total = 0;
        int read;
        while ((read = input.read(buffer)) >= 0) {
            total += read;
            if (total > MAX_BYTES)
                throw new IllegalArgumentException("document_unbounded");
            output.write(buffer, 0, read);
        }
        output.flush();
    }

    private void reply(String status, String detail) {
        String callback = getIntent().getStringExtra("callback");
        if (callback == null || callback.length() == 0) return;
        String mode = getIntent().getStringExtra("mode");
        UnityPlayer.UnitySendMessage(
                callback,
                "OnWorldMapDocumentResult",
                mode + "|" + status + "|" + (detail == null ? "" : detail));
    }
}
