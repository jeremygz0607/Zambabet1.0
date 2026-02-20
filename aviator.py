from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, InvalidSessionIdException, TimeoutException
from bs4 import BeautifulSoup
import time
import logging
import os

import config
import log_monitor
import scheduler

# Configure logging (console only - no log.log file)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def input_text(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(0.1)


def login(driver):
    try:
        logger.info(f"Navigating to {config.LOGIN_URL}")
        driver.get(config.LOGIN_URL)
        driver.find_element(By.CSS_SELECTOR, "button[type='button'].bg-button-primary.h-14").click()
        # Wait for login form; use name attributes (email / password) from the form
        username_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='email']"))
        )
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='password']"))
        )
        input_text(username_input, config.AVIATOR_USERNAME)
        input_text(password_input, config.AVIATOR_PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit'].bg-button-primary").click()
        logger.info("Logged in successfully")
        # Wait for promo modal's button row, then click Close (bg-button-secondary in that row only)
        time.sleep(1)
        try:
            close_btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[contains(@class,'mt-10') and contains(@class,'gap-x-6')]//button[contains(@class,'bg-button-secondary')]"
                ))
            )
            close_btn.click()
            logger.info("Closed promo modal")
            time.sleep(1)
        except Exception:
            logger.debug("No promo modal or Close button found")
        driver.find_element(By.CSS_SELECTOR, "button[type='button'].bg-button-primary").click()
        time.sleep(3)
        # Stats dropdown may be inside game iframe; try iframe first, then main page
        try:
            iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[loading='eager'][src*='spribe'], iframe[loading='eager'][src*='launch.spribegaming.com']"))
            )
            driver.switch_to.frame(iframe)
        except Exception:
            pass  # no iframe, stay on default content
        try:
            dropdown_toggle = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".button-block .dropdown-toggle"))
            )
            dropdown_toggle.click()
            logger.info("Opened stats dropdown")
        except Exception:
            logger.debug("Stats dropdown toggle not found")
        finally:
            driver.switch_to.default_content()
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise


def run_payout_script():
    """
    Main scraping loop.

    If the browser session becomes invalid (e.g. 'invalid session id'),
    the current driver is CLOSED and a NEW one is created in the next
    iteration. This prevents multiple dead sessions from piling up
    and keeps memory usage stable.
    """
    
    while True:
        driver = None
        try:
            driver = Driver(
                headless=True,
                undetectable=True,
                incognito=True,
            )

            login(driver)
            logger.info(f"Navigating to {config.LOGIN_URL}")
            driver.get(config.LOGIN_URL)

            previous_payout_list = None
            iframe_logged = False
            # Spribe game iframe: match by src (loading attribute may vary by site)
            IFRAME_SELECTOR = "iframe[loading='eager'][src*='spribe'], iframe[loading='eager'][src*='launch.spribegaming.com']"
            while True:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, IFRAME_SELECTOR))
                    )
                    if not iframe_logged:
                        logger.info("Switched to game iframe")
                        iframe_logged = True

                    try:
                        dropdown_toggle = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, ".button-block .dropdown-toggle"))
                        )
                        dropdown_toggle.click()
                        time.sleep(0.5)
                    except Exception:
                        logger.debug("Dropdown toggle not found or already open")

                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    payouts_wrapper = soup.find("div", class_="payouts-wrapper")
                    payouts = (
                        payouts_wrapper.find_all("div", class_="payout ng-star-inserted")
                        if payouts_wrapper
                        else []
                    )

                    if payouts:
                        payout_amount_list = [p.text.strip() for p in payouts]
                        previous_payout_list, had_new = log_monitor.process_payout_list(
                            payout_amount_list, previous_payout_list
                        )
                        if had_new:
                            logger.info(
                                f"Found {len(payouts)} payouts | {payout_amount_list}"
                            )
                    else:
                        logger.warning(config.LOG_NO_PAYOUTS_MSG)

                    driver.switch_to.default_content()
                    time.sleep(0.5)

                except TimeoutException:
                    logger.warning("Game iframe not found yet, retrying in 5s...")
                    driver.switch_to.default_content()
                    time.sleep(5)
                except (InvalidSessionIdException, WebDriverException) as we:
                    logger.error(
                        f"WebDriver session error (will restart browser): {we}",
                        exc_info=True,
                    )
                    break

        except Exception as e:
            logger.error(f"Error during script execution: {e}", exc_info=True)

        finally:
            if driver is not None:
                try:
                    driver.quit()
                    logger.info("WebDriver closed")
                except Exception:
                    pass

        logger.info("Waiting 10 seconds before restarting payout script...")
        time.sleep(10)


if not config.AVIATOR_USERNAME or not config.AVIATOR_PASSWORD:
    logger.error("Set AVIATOR_USERNAME and AVIATOR_PASSWORD environment variables. Exiting.")
    raise SystemExit(1)

if not config.MONGODB_URI:
    logger.error("Set MONGODB_URI environment variable. Exiting.")
    raise SystemExit(1)

if not log_monitor.init_mongodb():
    logger.error("MongoDB initialization failed. Exiting.")
    raise SystemExit(1)

logger.info("Script started (direct DB mode - no log file)")

try:
    run_payout_script()
finally:
    try:
        scheduler.post_shutdown_summary()
    except Exception as e:
        logger.warning(f"Could not post shutdown summary: {e}")
    scheduler.shutdown()
    log_monitor.close_mongodb()
    try:
        if os.path.isfile(config.PID_FILE):
            os.remove(config.PID_FILE)
            logger.info(f"Removed {config.PID_FILE}")
    except Exception:
        pass
