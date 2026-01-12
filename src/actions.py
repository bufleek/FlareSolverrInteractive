import logging
import random
import time
from typing import Any, Dict, List, Optional

from selenium.common import TimeoutException, NoSuchElementException, ElementNotInteractableException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class ActionResult:
    """Result of a single action execution"""
    def __init__(self, index: int, action_type: str, status: str, duration: int = 0, 
                 message: str = "", selector: str = None, error: str = None):
        self.index = index
        self.type = action_type
        self.status = status  # 'success', 'failed', 'skipped'
        self.duration = duration
        self.message = message
        self.selector = selector
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "index": self.index,
            "type": self.type,
            "status": self.status,
            "duration": self.duration,
            "message": self.message
        }
        if self.selector:
            result["selector"] = self.selector
        if self.error:
            result["error"] = self.error
        return result


class ActionExecutionResults:
    """Results of all actions execution"""
    def __init__(self):
        self.details: List[ActionResult] = []
        self.executed = 0
        self.successful = 0
        self.failed = 0
        self.skipped = 0

    def add_result(self, result: ActionResult):
        self.details.append(result)
        if result.status == 'success':
            self.successful += 1
            self.executed += 1
        elif result.status == 'failed':
            self.failed += 1
            self.executed += 1
        elif result.status == 'skipped':
            self.skipped += 1

    @property
    def summary(self) -> str:
        return f"{self.executed} executed, {self.successful} successful, {self.failed} failed, {self.skipped} skipped"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executed": self.executed,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "details": [r.to_dict() for r in self.details]
        }


def _get_element(driver: WebDriver, selector: str, timeout: int = 10):
    """Find element by CSS selector or XPath"""
    try:
        # Try CSS selector first
        if selector.startswith('//') or selector.startswith('(//'):
            # XPath
            return WebDriverWait(driver, timeout / 1000.0).until(
                EC.presence_of_element_located((By.XPATH, selector))
            )
        else:
            # CSS selector
            return WebDriverWait(driver, timeout / 1000.0).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
    except TimeoutException:
        raise NoSuchElementException(f"Element not found: {selector}")


def _element_exists(driver: WebDriver, selector: str) -> bool:
    """Check if element exists in DOM"""
    try:
        if selector.startswith('//') or selector.startswith('(//'):
            elements = driver.find_elements(By.XPATH, selector)
        else:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
        return len(elements) > 0
    except Exception:
        return False


def _element_visible(driver: WebDriver, selector: str) -> bool:
    """Check if element is visible"""
    try:
        if selector.startswith('//') or selector.startswith('(//'):
            element = driver.find_element(By.XPATH, selector)
        else:
            element = driver.find_element(By.CSS_SELECTOR, selector)
        return element.is_displayed()
    except Exception:
        return False


def _evaluate_condition(driver: WebDriver, condition: Optional[Dict[str, Any]]) -> bool:
    """Evaluate action condition"""
    if not condition:
        return True

    if 'ifExists' in condition:
        return _element_exists(driver, condition['ifExists'])
    elif 'ifNotExists' in condition:
        return not _element_exists(driver, condition['ifNotExists'])
    elif 'ifVisible' in condition:
        return _element_visible(driver, condition['ifVisible'])
    elif 'ifHidden' in condition:
        return not _element_visible(driver, condition['ifHidden'])
    elif 'ifTextMatches' in condition:
        import re
        selector = condition['ifTextMatches'].get('selector')
        pattern = condition['ifTextMatches'].get('pattern')
        try:
            element = _get_element(driver, selector, timeout=2000)
            return bool(re.search(pattern, element.text))
        except Exception:
            return False
    elif 'ifUrlMatches' in condition:
        import re
        pattern = condition['ifUrlMatches']
        return bool(re.search(pattern, driver.current_url))
    elif 'ifCustom' in condition:
        # Execute custom JavaScript condition
        try:
            result = driver.execute_script(condition['ifCustom'])
            return bool(result)
        except Exception:
            return False

    return True


def _execute_wait_action(driver: WebDriver, action: Dict[str, Any]) -> str:
    """Execute wait action"""
    wait_for = action.get('for', {})
    
    # Simple time-based wait
    if 'time' in wait_for:
        time.sleep(wait_for['time'] / 1000.0)
        return f"Waited {wait_for['time']}ms"
    
    # Element state waits
    if 'selector' in wait_for:
        selector = wait_for['selector']
        state = wait_for.get('state', 'visible')
        timeout = wait_for.get('timeout', 10000) / 1000.0
        
        if state == 'visible':
            if selector.startswith('//') or selector.startswith('(//'):
                WebDriverWait(driver, timeout).until(
                    EC.visibility_of_element_located((By.XPATH, selector))
                )
            else:
                WebDriverWait(driver, timeout).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
            return f"Waited for element {selector} to be visible"
        elif state == 'hidden':
            if selector.startswith('//') or selector.startswith('(//'):
                WebDriverWait(driver, timeout).until(
                    EC.invisibility_of_element_located((By.XPATH, selector))
                )
            else:
                WebDriverWait(driver, timeout).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, selector))
                )
            return f"Waited for element {selector} to be hidden"
        elif state == 'present':
            _get_element(driver, selector, timeout=int(timeout * 1000))
            return f"Waited for element {selector} to be present"
    
    # Event-based waits
    if 'event' in wait_for:
        event = wait_for['event']
        timeout = wait_for.get('timeout', 30000) / 1000.0
        
        if event == 'load':
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            return "Waited for page load"
        elif event == 'DOMContentLoaded':
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') in ['interactive', 'complete']
            )
            return "Waited for DOM content loaded"
        
    
    # URL change wait
    if 'urlChange' in wait_for:
        current_url = driver.current_url
        timeout = wait_for.get('timeout', 10000) / 1000.0
        WebDriverWait(driver, timeout).until(lambda d: d.current_url != current_url)
        return f"Waited for URL change from {current_url}"
    
    # Default: short wait
    time.sleep(0.5)
    return "Default wait executed"


def _execute_click_action(driver: WebDriver, action: Dict[str, Any]) -> str:
    """Execute click action with stealth patterns"""
    selector = action['selector']
    timeout = action.get('timeout', 10000)
    
    # Wait for element to be clickable
    element = _get_element(driver, selector, timeout=timeout)
    
    # Scroll element into view
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(random.uniform(0.1, 0.3))  # Random pause after scroll
    
    # Use ActionChains for human-like clicking
    actions = ActionChains(driver)
    
    # Add random offset for more human-like behavior
    offset_x = random.randint(-5, 5)
    offset_y = random.randint(-5, 5)
    
    actions.move_to_element_with_offset(element, offset_x, offset_y).click().perform()
    
    return f"Clicked element {selector}"


def _execute_type_action(driver: WebDriver, action: Dict[str, Any]) -> str:
    """Execute type action with human-like typing"""
    selector = action['selector']
    value = action['value']
    timeout = action.get('timeout', 10000)
    clear = action.get('clear', True)
    
    # Wait for element
    element = _get_element(driver, selector, timeout=timeout)
    
    # Scroll into view and focus
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(random.uniform(0.1, 0.2))
    
    # Clear existing text if requested
    if clear:
        element.clear()
        time.sleep(random.uniform(0.05, 0.15))
    
    # Use ActionChains for human-like typing
    actions = ActionChains(driver)
    actions.click(element)
    
    # Type with random delays between characters
    for char in value:
        actions.send_keys(char)
        actions.pause(random.uniform(0.05, 0.15))
    
    actions.perform()
    
    return f"Typed into {selector}"


def _execute_execute_script_action(driver: WebDriver, action: Dict[str, Any]) -> str:
    """Execute custom JavaScript"""
    script = action['script']
    result = driver.execute_script(script)
    return f"Executed script, result: {result}"


def _execute_press_enter_action(driver: WebDriver, action: Dict[str, Any]) -> str:
    """Execute press enter action on an element or active element"""
    selector = action.get('selector')
    timeout = action.get('timeout', 10000)
    
    if selector:
        # Press enter on a specific element
        element = _get_element(driver, selector, timeout=timeout)
        
        # Scroll into view
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(random.uniform(0.1, 0.2))
        
        # Use ActionChains to send Enter key
        actions = ActionChains(driver)
        actions.click(element).pause(random.uniform(0.05, 0.15))
        actions.send_keys(Keys.ENTER).perform()
        
        return f"Pressed Enter on {selector}"
    else:
        # Press enter on the currently active/focused element
        actions = ActionChains(driver)
        actions.send_keys(Keys.ENTER).perform()
        
        return "Pressed Enter on active element"


def _execute_single_action(driver: WebDriver, action: Dict[str, Any], index: int) -> ActionResult:
    """Execute a single action"""
    start_time = time.time()
    action_type = action.get('type')
    selector = action.get('selector')
    
    try:
        # Evaluate condition
        condition = action.get('condition')
        if not _evaluate_condition(driver, condition):
            duration = int((time.time() - start_time) * 1000)
            return ActionResult(
                index=index,
                action_type=action_type,
                status='skipped',
                duration=duration,
                message=f"Condition not met for {action_type} action",
                selector=selector
            )
        
        # Execute action based on type
        if action_type == 'wait':
            message = _execute_wait_action(driver, action)
        elif action_type == 'click':
            message = _execute_click_action(driver, action)
        elif action_type == 'type':
            message = _execute_type_action(driver, action)
        elif action_type == 'press_enter':
            message = _execute_press_enter_action(driver, action)
        elif action_type == 'execute_script':
            message = _execute_execute_script_action(driver, action)
        else:
            raise ValueError(f"Unknown action type: {action_type}")
        
        # Wait after action if specified
        wait_after = action.get('waitAfter', 0)
        if wait_after > 0:
            time.sleep(wait_after / 1000.0)
        
        duration = int((time.time() - start_time) * 1000)
        return ActionResult(
            index=index,
            action_type=action_type,
            status='success',
            duration=duration,
            message=message,
            selector=selector
        )
        
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        error_msg = str(e)
        logging.warning(f"Action {index} ({action_type}) failed: {error_msg}")
        
        return ActionResult(
            index=index,
            action_type=action_type,
            status='failed',
            duration=duration,
            message=f"Action failed: {error_msg}",
            selector=selector,
            error=error_msg
        )


def _execute_action_group(driver: WebDriver, action_group: Dict[str, Any], 
                          base_index: int) -> tuple[List[ActionResult], int]:
    """Execute a group of actions with optional condition"""
    results = []
    
    # Evaluate group condition if present
    group_condition = action_group.get('condition')
    if group_condition and not _evaluate_condition(driver, group_condition):
        # Skip entire group
        steps = action_group.get('steps', [])
        for i, step in enumerate(steps):
            result = ActionResult(
                index=base_index + i,
                action_type=step.get('type', 'unknown'),
                status='skipped',
                message=f"Group condition not met",
                selector=step.get('selector')
            )
            results.append(result)
        return results, len(steps)
    
    # Execute steps in the group
    steps = action_group.get('steps', [])
    continue_on_group_error = action_group.get('continueOnError', False)
    
    for i, step in enumerate(steps):
        result = _execute_single_action(driver, step, base_index + i)
        results.append(result)
        
        # Check if we should stop on error
        if result.status == 'failed':
            continue_on_error = step.get('continueOnError', continue_on_group_error)
            if not continue_on_error:
                # Stop executing remaining steps in this group
                # Mark remaining steps as skipped
                for j in range(i + 1, len(steps)):
                    skipped = ActionResult(
                        index=base_index + j,
                        action_type=steps[j].get('type', 'unknown'),
                        status='skipped',
                        message=f"Skipped due to previous failure",
                        selector=steps[j].get('selector')
                    )
                    results.append(skipped)
                break
        
        # Add small random pause between actions for stealth
        time.sleep(random.uniform(0.1, 0.3))
    
    return results, len(steps)


def execute_actions(actions: List[Dict[str, Any]], driver: WebDriver) -> ActionExecutionResults:
    """
    Execute a list of actions on the WebDriver
    
    Args:
        actions: List of action definitions or action groups
        driver: Selenium WebDriver instance
        
    Returns:
        ActionExecutionResults with execution details
    """
    results = ActionExecutionResults()
    current_index = 0
    
    for action in actions:
        # Check if this is an action group (has 'steps' key) or single action
        if 'steps' in action:
            # This is an action group
            group_results, steps_count = _execute_action_group(driver, action, current_index)
            for result in group_results:
                results.add_result(result)
            current_index += steps_count
        else:
            # Single action
            result = _execute_single_action(driver, action, current_index)
            results.add_result(result)
            current_index += 1
            
            # Check if we should stop on error
            if result.status == 'failed':
                continue_on_error = action.get('continueOnError', False)
                if not continue_on_error:
                    logging.error(f"Stopping action execution due to failure at index {result.index}")
                    break
            
            # Add small random pause between actions
            time.sleep(random.uniform(0.1, 0.3))
    
    return results
