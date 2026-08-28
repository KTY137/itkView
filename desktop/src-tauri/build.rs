fn main() {
    for name in [
        "ITKFLOW_PRODUCT_VARIANT",
        "ITKFLOW_DESKTOP_PRODUCT_NAME",
        "ITKFLOW_DESKTOP_DATA_SLUG",
        "ITKFLOW_DESKTOP_DATA_DIR_ENV",
        "ITKFLOW_DESKTOP_SIDECAR_NAME",
    ] {
        println!("cargo:rerun-if-env-changed={name}");
    }
    tauri_build::build()
}
