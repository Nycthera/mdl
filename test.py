import requests
import os

def download_image(url, save_folder="downloads"):
    try:
        os.makedirs(save_folder, exist_ok=True)
        filename = url.split("/")[-1]
        save_path = os.path.join(save_folder, filename)

        if os.path.exists(save_path):
            print(f"File '{filename}' already exists. Skipping download.")
            return

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/141.0.0.0 Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors

        with open(save_path, "wb") as f:
            f.write(response.content)

        print(f"Image downloaded successfully: {save_path}")

    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error downloading image: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

# Example usage
download_image("https://img-r1.2xstorage.com/bleach-colored/1/0.webp")
